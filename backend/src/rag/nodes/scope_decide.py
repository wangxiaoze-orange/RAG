"""⑤ 文档直读判断 + 均匀抽样（用户勾选文档 + 摘要类问题 → 直读全文概要）
- scope_decide_node：判定 direct_scope（有勾选文档 && 含摘要词）
- document_scope_node：预算 18 片（可配），每文档 max(4, 18/文档数) 均匀抽样
  排序分 1/(i+1) 递增（越靠前越高），走顺序分融合（替代 RRF）
- 抽样内容为空 → 回退主链路（direct_scope 置 False）
"""
import logging

from sqlalchemy import select

from src.config.config_center import config_center
from src.db.models import KbChunk
from src.db.session import async_session_maker
from src.rag.nodes._common import emit_stage
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig

logger = logging.getLogger(__name__)

SUMMARY_WORDS = ["总结", "概述", "概括", "讲了什么", "主要内容", "要点", "摘要", "有哪些内容", "目录", "都说了什么", "看看"]


async def scope_decide_node(state: ChatState, config: RunnableConfig) -> dict:
    """⑤ 直读判断：勾选文档 + 摘要词 → 走 document_scope 路径"""
    question = state["question"]
    kb_ids = state.get("kb_ids") or []
    direct = bool(kb_ids) and any(w in question for w in SUMMARY_WORDS)
    if direct:
        logger.info("命中文档直读: kb_ids=%s", kb_ids)
    return {"direct_scope": direct}


async def document_scope_node(state: ChatState, config: RunnableConfig) -> dict:
    """⑤ 均匀抽样直读：按文档数分配切片预算，等距采样（覆盖全文而非头部）"""
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "scope", "文档直读（均匀抽样）")

    budget = await config_center.get_int("rag.document_scope_chunk_budget", 18)
    kb_ids = state.get("kb_ids") or []
    if not kb_ids:
        return {"scope_chunks": [], "direct_scope": False}

    # 一次拉取目标库全部切片（id/chunk_index/content/元信息），内存分组均匀抽样
    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(
                    KbChunk.id, KbChunk.doc_id, KbChunk.doc_name, KbChunk.chunk_index,
                    KbChunk.page_number, KbChunk.section_title, KbChunk.content,
                ).where(KbChunk.kb_id.in_(kb_ids)).order_by(KbChunk.doc_id, KbChunk.chunk_index)
            )
        ).all()

    by_doc: dict[int, list] = {}
    for r in rows:
        by_doc.setdefault(r.doc_id, []).append(r)
    if not by_doc:
        return {"scope_chunks": [], "direct_scope": False}

    per_doc = max(4, budget // len(by_doc))
    sampled: list[dict] = []
    for doc_id, doc_rows in by_doc.items():
        n = len(doc_rows)
        step = max(1, n // per_doc)
        for i in range(0, n, step):
            r = doc_rows[i]
            sampled.append({
                "chunk_id": str(r.id),
                "doc_id": r.doc_id,
                "doc_name": r.doc_name,
                "chunk_index": r.chunk_index,
                "page_number": r.page_number,
                "section_title": r.section_title,
                "content": r.content,
                "source_type": "scope",
                "score": 1.0 / (len(sampled) + 1),  # 顺序分：越靠前越高
            })
            if len(sampled) >= budget:
                break
        if len(sampled) >= budget:
            break

    # 内容为空 → 回退主链路
    if not sampled:
        return {"scope_chunks": [], "direct_scope": False}

    ctx.sink.emit("scope", {
        "direct": True,
        "budget": budget,
        "docs": len(by_doc),
        "per_doc": per_doc,
        "sampled": len(sampled),
    })
    return {"scope_chunks": sampled, "direct_scope": True}
