"""网页检索：DuckDuckGo（ddgs），结果仅作参考"""
import asyncio
import logging
from functools import lru_cache

from src.config.config_center import config_center

logger = logging.getLogger(__name__)


async def web_search(query: str, max_results: int = 5, site: str | None = None) -> list[dict]:
    """搜索引擎检索网页。失败时返回空列表（降级，不让检索失败影响主流程）"""
    from src.config.settings import settings  # noqa: F401
    enabled = await config_center.get_bool("rag.feature.web_search_enabled", True)
    if not enabled:
        logger.info("web 检索已通过特征开关关闭")
        return []
    timeout = await config_center.get_int("rag.web_search_timeout_seconds", 8)
    full_query = f"site:{site} {query}" if site else query

    def _search() -> list[dict]:
        try:
            from ddgs import DDGS
            with DDGS(timeout=timeout) as ddgs:
                results = list(ddgs.text(full_query, max_results=max_results, region="cn-zh"))
            return [
                {
                    "url": r.get("href", ""),
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "published_at": r.get("published") or None,
                }
                for r in results
                if r.get("href")
            ]
        except Exception as e:  # noqa: BLE001
            logger.warning("web 检索失败: %s", e)
            return []

    try:
        return await asyncio.wait_for(asyncio.to_thread(_search), timeout=timeout + 2)
    except asyncio.TimeoutError:
        logger.warning("web 检索超时")
        return []


@lru_cache(maxsize=1)
def get_web_search():
    return web_search
