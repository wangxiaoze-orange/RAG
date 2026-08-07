"""⑯ 收尾：高频问题写缓存 + 经验库自动沉淀 + 消息持久化（答案/来源/推理链/工具日志/审查日志）+ SSE done
- 缓存写入条件：freq ≥ min_freq（防穿透阈值）&& 检索命中 && 非兜底/概览/直读路径
- 经验库沉淀：同条件自动入 qa_faq（待审核），管理员发布后直读
- qa_message 持久化 assistant 消息（全量埋点字段）
- ToolCallLog / SelfReflectionLog 落库（AgentTrace 由 P4 节点包装器写）
"""
import datetime
import logging
import time

from src.config.config_center import config_center
from src.db.models import QaMessage, SelfReflectionLog, ToolCallLog
from src.db.session import async_session_maker
from src.rag.nodes._common import emit_stage
from src.rag.services import faq_store, rag_cache
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig

logger = logging.getLogger(__name__)

MIN_FREQ_FOR_CACHE_WRITE = 3
CACHEABLE_PATHS = {"standard", "document_scope"}


def _sources_from_references(references: list[dict]) -> list[dict]:
    """来源列表（前端展示用）：文档名/章节/页码/分数/来源类型 + 内容预览"""
    sources = []
    for c in references or []:
        content = c.get("content") or ""
        sources.append({
            "doc_name": c.get("doc_name") or c.get("filename") or "未知文档",
            "section_title": c.get("section_title"),
            "page_number": c.get("page_number"),
            "score": c.get("score"),
            "source_type": c.get("source_type", "kb"),
            "hit_routes": c.get("hit_routes"),
            "web_url": c.get("web_url"),
            "preview": content[:300],
        })
    return sources


async def finish_node(state: ChatState, config: RunnableConfig) -> dict:
    """⑯ 收尾节点（终节点）"""
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "finish", "收尾")

    answer = state.get("answer") or ""
    conversation_id = state.get("conversation_id")
    message_id = state.get("message_id")
    path_type = state.get("path_type") or "standard"
    now = datetime.datetime.now(datetime.timezone.utc)
    elapsed_ms = int((time.monotonic() - state.get("start_time", time.monotonic())) * 1000)

    # ---- 高频问题写缓存（防穿透：freq ≥ 阈值才写）----
    min_freq = await config_center.get_int("rag.cache_write_min_freq", MIN_FREQ_FOR_CACHE_WRITE)
    cache_written = False
    freq = state.get("freq") or 0
    normalized = state.get("normalized_question") or ""
    retrieval_hit = bool(state.get("retrieval_hit"))
    if (
        not state.get("cache_hit")
        and freq >= min_freq
        and retrieval_hit
        and path_type in CACHEABLE_PATHS
        and normalized
    ):
        try:
            kb_scope = rag_cache.scope_hash(state.get("kb_ids"))
            await rag_cache.set_cache(normalized, kb_scope, {
                "answer": answer,
                "sources": _sources_from_references(state.get("references") or []),
                "elapsed_ms": elapsed_ms,
            })
            cache_written = True
            logger.info("缓存写入: freq=%d q=%s", freq, normalized)
        except Exception as e:  # noqa: BLE001
            logger.warning("缓存写入失败: %s", e)

    # ---- 持久化 assistant 消息（全量埋点）----
    sources = _sources_from_references(state.get("references") or [])

    # ---- 经验库自动沉淀（待审核，管理员发布后直读）----
    faq_written = False
    faq_enabled = await config_center.get_bool("rag.feature.faq_enabled", True)
    if (
        faq_enabled
        and not state.get("cache_hit")
        and freq >= min_freq
        and retrieval_hit
        and path_type in CACHEABLE_PATHS
        and normalized
        and answer
    ):
        try:
            faq_id = await faq_store.settle_faq(
                question=state["question"],
                normalized=normalized,
                rewritten=state.get("rewritten_query"),
                answer=answer,
                sources=sources,
                kb_ids=state.get("kb_ids"),
                freq=freq,
            )
            faq_written = faq_id is not None
        except Exception as e:  # noqa: BLE001
            logger.warning("经验库沉淀失败: %s", e)

    async with async_session_maker() as session:
        if conversation_id and message_id:
            msg = QaMessage(
                conversation_id=conversation_id,
                user_id=ctx.user_id,
                role="assistant",
                content=answer,
                question_normalized=normalized or None,
                freq=freq,
                cache_hit=1 if state.get("cache_hit") else 0,
                cache_written=1 if cache_written else 0,
                path_type=path_type,
                confidence=state.get("confidence"),
                retrieval_hit=1 if retrieval_hit else 0,
                intent_scope=state.get("intent_scope"),
                intent_labels=state.get("intent_labels"),
                sources=sources or None,
                agent_trace=(state.get("agent_trace") or [])[:50],
                tool_calls=(state.get("tool_logs") or [])[:50],
                reflection=state.get("reflection"),
                latency_ms=elapsed_ms,
                error_code=state.get("error"),
            )
            session.add(msg)
            await session.flush()

            # 工具调用日志（逐条）
            for t in (state.get("tool_logs") or []):
                session.add(ToolCallLog(
                    message_id=msg.id,
                    conversation_id=conversation_id,
                    tool_name=t.get("tool", ""),
                    source=state.get("retrieval_source") or "agent",
                    input={"query": t.get("args")},
                    output={"summary": t.get("summary")},
                    latency_ms=t.get("latency_ms"),
                    status="ok",
                ))
            # 审查日志
            if state.get("reflection"):
                ref = state["reflection"]
                session.add(SelfReflectionLog(
                    message_id=msg.id,
                    conversation_id=conversation_id,
                    question=state["question"][:2000],
                    answer=answer[:4000],
                    conclusion=ref.get("conclusion") or "pass",
                    issues=ref.get("issues"),
                    action=ref.get("action") or "none",
                ))
            await session.commit()
            assistant_message_id = msg.id
        else:
            assistant_message_id = None

    # ---- SSE done ----
    ctx.sink.emit("done", {
        "answer": answer,  # 兜底：token 事件若丢失/被缓冲，前端可直接整段渲染
        "conversation_id": conversation_id,
        "message_id": assistant_message_id,
        "path_type": path_type,
        "sources": sources,
        "confidence": state.get("confidence"),
        "retrieval_hit": retrieval_hit,
        "use_fallback": bool(state.get("use_fallback")),
        "cache_hit": bool(state.get("cache_hit")),
        "cache_written": cache_written,
        "faq_written": faq_written,
        "reflection": state.get("reflection"),
        "tool_calls": len(state.get("tool_logs") or []),
        "elapsed_ms": elapsed_ms,
    })
    return {
        "sources": sources,
        "cache_written": cache_written,
        "assistant_message_id": assistant_message_id,
    }
