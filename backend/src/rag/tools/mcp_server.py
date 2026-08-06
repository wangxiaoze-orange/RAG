"""FastMCP 独立服务端：把检索工具集暴露给外部 MCP 客户端（如 Claude Code）
启动（在 backend/ 目录下）：
    python -m src.rag.tools.mcp_server
然后客户端配置：mcp {
    server "rag-search" {
        command = "python"
        args = ["-m", "src.rag.tools.mcp_server"]
    }
}
"""
import asyncio
import logging

from mcp.server.fastmcp import FastMCP

from src.config.settings import settings
from src.core.logging import setup_logging
from src.rag.tools.rag_toolkit import (
    TOOL_DOC_SEARCH,
    TOOL_KEYWORD_SEARCH,
    TOOL_RECALL_MEMORY,
    TOOL_WEB_SEARCH,
    doc_search_service,
    keyword_search_service,
    recall_memory_service,
    web_search_service,
)

setup_logging()
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "rag-search",
    host=settings.mcp_host,
    port=settings.mcp_port,
)


@mcp.tool(name=TOOL_DOC_SEARCH)
async def doc_search(query: str, top_k: int = 10, kb_ids: list[int] | None = None) -> dict:
    """对知识库执行语义向量检索，返回与问题语义最相关的文档切片。适合理解型、语义相似的问题。

    Args:
        query: 检索问题
        top_k: 返回条数（1-30）
        kb_ids: 限定知识库 ID 列表，空则检索全部
    """
    embed_fn = None
    try:
        # 需要嵌入模型：注入默认供应商嵌入
        from src.providers.manager import provider_manager
        from src.providers.factory import embed_texts
        provider = await provider_manager.get_default()
        if provider:
            async def embed_fn(text: str) -> list[float]:
                vectors = await embed_texts(provider, [text])
                return vectors[0]
    except Exception as e:  # noqa: BLE001
        logger.warning("MCP doc_search 嵌入初始化失败: %s", e)
    return await doc_search_service(query, kb_ids=kb_ids, top_k=top_k, embed_fn=embed_fn)


@mcp.tool(name=TOOL_KEYWORD_SEARCH)
async def keyword_search(query: str, top_k: int = 10, kb_ids: list[int] | None = None) -> dict:
    """对知识库执行 BM25 关键词检索，适合精确术语、型号、专有名词查询。

    Args:
        query: 检索关键词
        top_k: 返回条数（1-30）
        kb_ids: 限定知识库 ID 列表，空则检索全部
    """
    return await keyword_search_service(query, kb_ids=kb_ids, top_k=top_k)


@mcp.tool(name=TOOL_WEB_SEARCH)
async def web_search(query: str, max_results: int = 5) -> dict:
    """搜索互联网补充最新/外部信息。结果仅作参考，不保证准确。

    Args:
        query: 搜索关键词
        max_results: 返回条数（1-10）
    """
    return await web_search_service(query, max_results=max_results)


@mcp.tool(name=TOOL_RECALL_MEMORY)
async def recall_memory(user_id: int, keyword: str | None = None) -> dict:
    """查询用户长期记忆（偏好/过敏/称呼/回答语言）。

    Args:
        user_id: 目标用户 ID
        keyword: 记忆检索关键词，空则返回全部
    """
    return await recall_memory_service(user_id, keyword=keyword)


def main() -> None:
    logger.info("MCP 服务端启动: %s:%d", settings.mcp_host, settings.mcp_port)
    asyncio.run(mcp.run())


if __name__ == "__main__":
    main()
