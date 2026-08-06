"""LangGraph 图拓扑（①-⑯ 流水线）：
session → cache_check →{命中→cache_replay, 未中→overview_detect} → overview_answer(短路) / intent
→ rewrite → scope_decide →{直读→document_scope, 否则→agent_retrieve(ReAct)}
→{失败→router_fallback} → merge → rrf_fusion →{直读→compress, 否则→rerank} → compress
→ safety_guard →{未命中→knowledge_fallback, 命中→assemble} → generate → self_reflection → finish

每个节点经 _traced 包装：AgentTrace 表异步落库（不阻塞主链路）
"""
import asyncio
import functools
import logging
import time

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from src.db.models import AgentTrace
from src.db.session import async_session_maker
from src.rag.nodes import (
    agent_retrieve,
    assemble,
    cache_check,
    compress,
    finish,
    generate,
    intent,
    memory_extract,
    merge,
    overview,
    rerank,
    rewrite,
    rrf_fusion,
    router_fallback,
    safety_guard,
    scope_decide,
    self_reflection,
    session,
)
from src.rag.state import ChatState

logger = logging.getLogger(__name__)

# 已创建但未完成的后台 AgentTrace 写任务（防止被 GC）
_PENDING_TRACES: set[asyncio.Task] = set()


def _traced(name: str, node_fn):
    """节点包装器：调用原节点，异步记录 AgentTrace（status/latency），异常记录后重抛"""
    @functools.wraps(node_fn)
    async def wrapped(state: ChatState, config: RunnableConfig) -> dict:
        start = time.monotonic()
        status = "ok"
        error = None
        try:
            out = await node_fn(state, config)
            return out
        except Exception as e:  # noqa: BLE001
            status = "error"
            error = str(e)[:512]
            logger.exception("节点 %s 异常: %s", name, e)
            raise
        finally:
            entry = {
                "message_id": state.get("message_id") or 0,
                "conversation_id": state.get("conversation_id") or 0,
                "node_name": name,
                "latency_ms": int((time.monotonic() - start) * 1000),
                "status": status,
            }
            if error:
                entry["output"] = {"error": error}

            async def _write(e: dict) -> None:
                try:
                    async with async_session_maker() as s:
                        s.add(AgentTrace(**e))
                        await s.commit()
                except Exception:  # noqa: BLE001
                    logger.warning("AgentTrace 落库失败（不影响主链路）")

            task = asyncio.create_task(_write(entry))
            _PENDING_TRACES.add(task)
            task.add_done_callback(_PENDING_TRACES.discard)

    return wrapped


# ---------- 条件边 ----------
def _after_cache_check(state: ChatState) -> str:
    if state.get("cache_hit"):
        return "cache_replay"
    # 未选择知识库 → 闲聊模式：跳过意图/检索链路，走空结果链路到常识兜底直接生成
    if not state.get("kb_ids"):
        return "merge"
    return "overview_detect"


def _after_overview(state: ChatState) -> str:
    return "overview_answer" if state.get("is_overview") else "intent"


def _after_scope_decide(state: ChatState) -> str:
    return "document_scope" if state.get("direct_scope") else "agent_retrieve"


def _after_agent_retrieve(state: ChatState) -> str:
    return "router_fallback" if state.get("retrieval_failed") else "merge"


def _after_fuse(state: ChatState) -> str:
    return "compress" if state.get("direct_scope") else "rerank"


def _after_safety(state: ChatState) -> str:
    return "knowledge_fallback" if not state.get("retrieval_hit") else "assemble"


def build_graph():
    """构建并编译 LangGraph（模块级缓存）"""
    g = StateGraph(ChatState)

    # 节点注册（全部经 AgentTrace 包装）
    g.add_node("session", _traced("session", session.session_node))
    g.add_node("cache_check", _traced("cache_check", cache_check.cache_check_node))
    g.add_node("cache_replay", _traced("cache_replay", cache_check.cache_replay_node))
    g.add_node("overview_detect", _traced("overview_detect", overview.overview_detect_node))
    g.add_node("overview_answer", _traced("overview_answer", overview.overview_answer_node))
    g.add_node("intent", _traced("intent", intent.intent_node))
    g.add_node("rewrite", _traced("rewrite", rewrite.rewrite_node))
    g.add_node("scope_decide", _traced("scope_decide", scope_decide.scope_decide_node))
    g.add_node("document_scope", _traced("document_scope", scope_decide.document_scope_node))
    g.add_node("agent_retrieve", _traced("agent_retrieve", agent_retrieve.agent_retrieve_node))
    g.add_node("router_fallback", _traced("router_fallback", router_fallback.router_fallback_node))
    g.add_node("merge", _traced("merge", merge.merge_node))
    g.add_node("rrf_fusion", _traced("rrf_fusion", rrf_fusion.rrf_fusion_node))
    g.add_node("rerank", _traced("rerank", rerank.rerank_node))
    g.add_node("compress", _traced("compress", compress.compress_node))
    g.add_node("safety_guard", _traced("safety_guard", safety_guard.safety_guard_node))
    g.add_node("knowledge_fallback", _traced("knowledge_fallback", safety_guard.knowledge_fallback_node))
    g.add_node("assemble", _traced("assemble", assemble.assemble_node))
    g.add_node("generate", _traced("generate", generate.generate_node))
    g.add_node("self_reflection", _traced("self_reflection", self_reflection.self_reflection_node))
    g.add_node("memory_extract", _traced("memory_extract", memory_extract.memory_extract_node))
    g.add_node("finish", _traced("finish", finish.finish_node))

    # 边：主线
    g.add_edge(START, "session")
    g.add_edge("session", "cache_check")
    g.add_conditional_edges("cache_check", _after_cache_check, {"cache_replay": "cache_replay", "overview_detect": "overview_detect", "merge": "merge"})
    g.add_edge("cache_replay", "finish")
    g.add_conditional_edges("overview_detect", _after_overview, {"overview_answer": "overview_answer", "intent": "intent"})
    g.add_edge("overview_answer", "finish")
    g.add_edge("intent", "memory_extract")
    g.add_edge("memory_extract", "rewrite")
    g.add_edge("rewrite", "scope_decide")
    g.add_conditional_edges("scope_decide", _after_scope_decide, {"document_scope": "document_scope", "agent_retrieve": "agent_retrieve"})
    g.add_edge("document_scope", "rrf_fusion")
    g.add_conditional_edges("agent_retrieve", _after_agent_retrieve, {"router_fallback": "router_fallback", "merge": "merge"})
    g.add_edge("router_fallback", "merge")
    g.add_edge("merge", "rrf_fusion")
    g.add_conditional_edges("rrf_fusion", _after_fuse, {"compress": "compress", "rerank": "rerank"})
    g.add_edge("rerank", "compress")
    g.add_edge("compress", "safety_guard")
    g.add_conditional_edges("safety_guard", _after_safety, {"knowledge_fallback": "knowledge_fallback", "assemble": "assemble"})
    g.add_edge("knowledge_fallback", "finish")
    g.add_edge("assemble", "generate")
    g.add_edge("generate", "self_reflection")
    g.add_edge("self_reflection", "finish")
    g.add_edge("finish", END)

    return g.compile()


# 模块级编译缓存（首请求编译，之后复用）
_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph
