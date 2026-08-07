"""⑦ 检索降级路径（QueryRouter 规则直调）：
ReAct 异常/零召回/特性关闭时，按意图 label 加权投票出的工具策略，直接调 service 层
（doc_search/keyword_search/web_search/recall_memory），带子问题多路检索
"""
import asyncio
import logging
import time

from src.rag.nodes._common import emit_stage
from src.rag.nodes.intent import weighted_vote_tools
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig
from src.rag.tools import rag_toolkit
from src.rag.tools.rag_toolkit import (
    TOOL_DOC_SEARCH,
    TOOL_KEYWORD_SEARCH,
    TOOL_RECALL_MEMORY,
    TOOL_WEB_SEARCH,
)

logger = logging.getLogger(__name__)

# scope → 工具策略（与 intent.py Layer 3 权重表同源）
SCOPE_TOOLS = {
    "kb": [TOOL_DOC_SEARCH, TOOL_KEYWORD_SEARCH],
    "web": [TOOL_WEB_SEARCH],
    "memory": [TOOL_RECALL_MEMORY],
    "mixed": [TOOL_DOC_SEARCH, TOOL_KEYWORD_SEARCH, TOOL_WEB_SEARCH],
    "chat": [],
}


async def router_fallback_node(state: ChatState, config: RunnableConfig) -> dict:
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "retrieve", "规则路由检索（降级）")

    scope = state.get("intent_scope", "kb")
    # 策略合并：LLM labels 加权投票优先，缺省按 scope 规则
    # （labels 为空时 tools 须先从 scope 取默认，避免引用未赋值的局部变量）
    tools = SCOPE_TOOLS.get(scope, SCOPE_TOOLS["kb"])
    if state.get("intent_labels"):
        tools = weighted_vote_tools(state["intent_labels"]) or tools

    queries = [state.get("rewritten_query") or state["question"]]
    if state.get("needs_decomposition") and state.get("sub_questions"):
        queries += state["sub_questions"][:2]  # 子问题最多并行 2 个，控制成本

    budgets: dict[str, int] = state.get("recall_budgets") or {}
    collector: dict[str, list] = {}
    tool_logs: list[dict] = []

    async def run_one(tool_name: str, query: str) -> None:
        start = time.monotonic()
        try:
            if tool_name == TOOL_DOC_SEARCH:
                r = await rag_toolkit.doc_search_service(query, kb_ids=ctx.kb_ids, user_id=ctx.user_id, top_k=budgets.get(tool_name, 10), embed_fn=ctx.embed_fn)
                hits = r.get("chunks", [])
            elif tool_name == TOOL_KEYWORD_SEARCH:
                r = await rag_toolkit.keyword_search_service(query, kb_ids=ctx.kb_ids, user_id=ctx.user_id, top_k=budgets.get(tool_name, 10))
                hits = r.get("chunks", [])
            elif tool_name == TOOL_WEB_SEARCH:
                r = await rag_toolkit.web_search_service(query, max_results=min(budgets.get(tool_name, 5), 10))
                hits = r.get("results", [])
            elif tool_name == TOOL_RECALL_MEMORY:
                r = await rag_toolkit.recall_memory_service(ctx.user_id)
                hits = r.get("memories", [])
            else:
                return
            collector.setdefault(tool_name, []).extend(hits)
            tool_logs.append({
                "tool": tool_name,
                "args": {"query": query},
                "summary": f"命中 {len(hits)} 条",
                "latency_ms": int((time.monotonic() - start) * 1000),
            })
            ctx.sink.emit("tool_call", {"name": tool_name, "args": {"query": query}, "summary": f"命中 {len(hits)} 条"})
        except Exception as e:  # noqa: BLE001
            logger.warning("规则路由 %s 失败: %s", tool_name, e)

    # 多路并发直调（每工具 × 主查询，子问题只打主工具避免爆炸）
    tasks = [run_one(t, queries[0]) for t in tools]
    tasks += [run_one(tools[0], q) for q in queries[1:]]
    await asyncio.gather(*tasks)

    hit_total = sum(len(v) for v in collector.values())
    ctx.sink.emit("retrieve", {"source": "router", "tool_calls": len(tool_logs), "hits": hit_total})
    return {
        "tool_results": dict(collector),
        "tool_logs": tool_logs,
        "retrieval_source": "router",
        "retrieval_failed": hit_total == 0,
    }
