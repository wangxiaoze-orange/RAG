"""⑧ 多路召回合并：把 tool_results（{tool_name: [chunks]}）规整为 recalls 列表
- 每个工具一路（list），保持路内顺序（RRF 依赖秩信息）
- web/memory 结果转 pseudo-chunk（无 chunk_id，用 url/content hash 做去重键）
- 每路打 source_type 标记（doc_search=vector / keyword_search=bm25 / web / memory）
"""
import hashlib
import logging

from src.rag.state import ChatState, RunnableConfig

logger = logging.getLogger(__name__)

# 路内来源标记
ROUTE_SOURCE = {
    "doc_search": "vector",
    "keyword_search": "bm25",
    "web_search": "web",
    "recall_memory": "memory",
}


def _pseudo_chunk(item: dict, source: str, rank: int) -> dict:
    """web/memory 结果 → pseudo-chunk（与 kb_chunk 对齐字段）"""
    if source == "web":
        title = item.get("title") or ""
        url = item.get("href") or item.get("url") or ""
        body = item.get("body") or item.get("snippet") or item.get("content") or ""
        return {
            "chunk_id": f"web:{hashlib.md5(url.encode()).hexdigest()[:16]}",
            "doc_name": title[:60] or url[:60],
            "section_title": "网页",
            "page_number": None,
            "content": body,
            "source_type": "web",
            "score": 1.0 / (rank + 1),
            "web_url": url,
        }
    # memory
    text = item.get("text") or str(item.get("content") or item)
    return {
        "chunk_id": f"mem:{hashlib.md5(text.encode()).hexdigest()[:16]}",
        "doc_name": "用户记忆",
        "section_title": item.get("mtype") or "记忆",
        "page_number": None,
        "content": text,
        "source_type": "memory",
        "score": 1.0 / (rank + 1),
    }


async def merge_node(state: ChatState, config: RunnableConfig) -> dict:
    """⑧ 合并：tool_results → recalls（多路列表），带来源标记"""
    tool_results = state.get("tool_results") or {}
    recalls: list[list[dict]] = []
    for tool_name, items in tool_results.items():
        source = ROUTE_SOURCE.get(tool_name, tool_name)
        route: list[dict] = []
        for rank, it in enumerate(items):
            if source in ("web", "memory"):
                route.append(_pseudo_chunk(it, source, rank))
            else:
                chunk = dict(it)
                chunk["source_type"] = source
                route.append(chunk)
        if route:
            recalls.append(route)
    return {"recalls": recalls}
