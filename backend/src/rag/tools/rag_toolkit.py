"""⑦ 检索工具集（双模式唯一实现）：
- 进程内：build_langchain_tools() 绑定到 ReAct Agent
- MCP 服务端：mcp_server.py 包装同一批函数对外暴露
四个工具：doc_search（向量）/ keyword_search（BM25）/ web_search（网页）/ recall_memory（记忆）
"""
import logging
import time
from typing import Any, Callable

from langchain_core.tools import StructuredTool

from src.rag.services.bm25_store import get_bm25_store
from src.rag.services.user_memory import list_memories
from src.rag.services.vector_store import get_vector_store
from src.rag.services.web_search import web_search as _web_search

logger = logging.getLogger(__name__)

# 工具名常量（推理链/日志统一引用）
TOOL_DOC_SEARCH = "doc_search"
TOOL_KEYWORD_SEARCH = "keyword_search"
TOOL_WEB_SEARCH = "web_search"
TOOL_RECALL_MEMORY = "recall_memory"


# ============ 核心实现（与 MCP/LangChain 无关的纯逻辑） ============
async def doc_search_service(
    query: str,
    kb_ids: list[int] | None = None,
    user_id: int | None = None,
    top_k: int = 10,
    embed_fn: Callable[[str], Any] | None = None,
) -> dict:
    """向量语义检索：query 嵌入 → Milvus 检索 → 结果列表
    embed_fn 由调用方注入（供应商嵌入客户端），未注入时返回空结果并告警
    """
    start = time.monotonic()
    if embed_fn is None:
        return {"chunks": [], "latency_ms": 0, "message": "未配置嵌入函数"}
    try:
        query_emb = await embed_fn(query)
        chunks = await get_vector_store().search(query_emb, kb_ids=kb_ids, top_k=top_k)
        return {"chunks": chunks, "latency_ms": int((time.monotonic() - start) * 1000)}
    except Exception as e:  # noqa: BLE001
        logger.warning("doc_search 失败: %s", e)
        return {"chunks": [], "latency_ms": int((time.monotonic() - start) * 1000), "error": str(e)}


async def keyword_search_service(
    query: str,
    kb_ids: list[int] | None = None,
    user_id: int | None = None,
    top_k: int = 10,
) -> dict:
    """BM25 关键词检索（jieba 分词），适合精确术语/型号/专名"""
    start = time.monotonic()
    try:
        chunks = await get_bm25_store().search(query, kb_ids=kb_ids, top_k=top_k)
        return {"chunks": chunks, "latency_ms": int((time.monotonic() - start) * 1000)}
    except Exception as e:  # noqa: BLE001
        logger.warning("keyword_search 失败: %s", e)
        return {"chunks": [], "latency_ms": int((time.monotonic() - start) * 1000), "error": str(e)}


async def web_search_service(
    query: str,
    max_results: int = 5,
    site: str | None = None,
) -> dict:
    """网页检索（DuckDuckGo），结果仅作参考"""
    start = time.monotonic()
    try:
        results = await _web_search(query, max_results=max_results, site=site)
        return {"results": results, "latency_ms": int((time.monotonic() - start) * 1000)}
    except Exception as e:  # noqa: BLE001
        logger.warning("web_search 失败: %s", e)
        return {"results": [], "latency_ms": int((time.monotonic() - start) * 1000), "error": str(e)}


async def recall_memory_service(
    user_id: int,
    keyword: str | None = None,
) -> dict:
    """用户长期记忆检索（偏好/过敏/称呼/回答语言）"""
    start = time.monotonic()
    try:
        memories = await list_memories(user_id, keyword=keyword)
        return {"memories": memories, "latency_ms": int((time.monotonic() - start) * 1000)}
    except Exception as e:  # noqa: BLE001
        logger.warning("recall_memory 失败: %s", e)
        return {"memories": [], "latency_ms": int((time.monotonic() - start) * 1000), "error": str(e)}


# ============ LangChain 工具包装（进程内 ReAct 使用） ============
def build_langchain_tools(
    *,
    kb_ids: list[int] | None = None,
    user_id: int | None = None,
    embed_fn: Callable[[str], Any] | None = None,
    tool_logger: Callable[[dict], None] | None = None,
    collector: dict[str, list] | None = None,
) -> list:
    """按请求上下文构建 4 个 LangChain 工具
    - kb_ids/user_id 闭包注入（ReAct 无法感知外部状态）
    - tool_logger 回调：每次调用记录 {tool,args,summary,latency_ms}，用于 tool_call_log 与 SSE tool_call 事件
    - collector: {tool_name: [...]} 结果收集器（ReAct 结束后据此汇合多路召回）
    """

    def _collect(name: str, payload: list) -> None:
        if collector is not None:
            collector.setdefault(name, []).extend(payload)

    async def _doc_search(query: str, top_k: int = 10) -> dict:
        start = time.monotonic()
        r = await doc_search_service(query, kb_ids=kb_ids, user_id=user_id, top_k=top_k, embed_fn=embed_fn)
        _collect(TOOL_DOC_SEARCH, r.get("chunks", []))
        if tool_logger:
            tool_logger({
                "tool": TOOL_DOC_SEARCH,
                "args": {"query": query, "top_k": top_k},
                "summary": f"命中 {len(r.get('chunks', []))} 条",
                "latency_ms": int((time.monotonic() - start) * 1000),
            })
        return r

    async def _keyword_search(query: str, top_k: int = 10) -> dict:
        start = time.monotonic()
        r = await keyword_search_service(query, kb_ids=kb_ids, top_k=top_k)
        _collect(TOOL_KEYWORD_SEARCH, r.get("chunks", []))
        if tool_logger:
            tool_logger({
                "tool": TOOL_KEYWORD_SEARCH,
                "args": {"query": query, "top_k": top_k},
                "summary": f"命中 {len(r.get('chunks', []))} 条",
                "latency_ms": int((time.monotonic() - start) * 1000),
            })
        return r

    async def _web_search(query: str, max_results: int = 5) -> dict:
        start = time.monotonic()
        r = await web_search_service(query, max_results=max_results)
        _collect(TOOL_WEB_SEARCH, r.get("results", []))
        if tool_logger:
            tool_logger({
                "tool": TOOL_WEB_SEARCH,
                "args": {"query": query, "max_results": max_results},
                "summary": f"获取 {len(r.get('results', []))} 条",
                "latency_ms": int((time.monotonic() - start) * 1000),
            })
        return r

    async def _recall_memory(keyword: str | None = None) -> dict:
        start = time.monotonic()
        r = await recall_memory_service(user_id, keyword=keyword)
        _collect(TOOL_RECALL_MEMORY, r.get("memories", []))
        if tool_logger:
            tool_logger({
                "tool": TOOL_RECALL_MEMORY,
                "args": {"keyword": keyword},
                "summary": f"回忆 {len(r.get('memories', []))} 条",
                "latency_ms": int((time.monotonic() - start) * 1000),
            })
        return r

    # langchain-core 1.x 起 tool() 不再接受 name/description 关键字参数，改用 StructuredTool.from_function
    # （四个包装函数均为 async，需传 coroutine=）
    return [
        StructuredTool.from_function(coroutine=_doc_search, name=TOOL_DOC_SEARCH, description="对知识库执行语义向量检索，返回与问题语义最相关的文档切片。适合理解型、语义相似的问题。"),
        StructuredTool.from_function(coroutine=_keyword_search, name=TOOL_KEYWORD_SEARCH, description="对知识库执行 BM25 关键词检索，适合精确术语、型号、专有名词查询。"),
        StructuredTool.from_function(coroutine=_web_search, name=TOOL_WEB_SEARCH, description="搜索互联网补充最新/外部信息。结果仅作参考，不保证准确。"),
        StructuredTool.from_function(coroutine=_recall_memory, name=TOOL_RECALL_MEMORY, description="查询用户长期记忆（偏好/过敏/称呼/回答语言）。仅当问题涉及用户个性化信息时调用。"),
    ]
