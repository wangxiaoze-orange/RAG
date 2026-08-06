"""把 rag.* 默认参数与供应商种子写入 etcd（幂等：已存在的 key 不覆盖）
用法（在 backend/ 目录下）：
    python scripts/seed_etcd.py
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config.etcd_client import get_etcd_client  # noqa: E402
from src.core.logging import setup_logging  # noqa: E402
from src.providers.base import ProviderConfig  # noqa: E402
from src.providers.manager import BUILTIN_PROVIDERS, PROVIDER_PREFIX  # noqa: E402

setup_logging()
logger = logging.getLogger("seed_etcd")

# rag.* 默认参数（与 deploy/etcd/seed-config.sh 一致）
DEFAULT_CONFIGS = {
    "/config/rag/cache_min_freq": "3",
    "/config/rag/cache_ttl_seconds": "604800",
    "/config/rag/document_scope_chunk_budget": "18",
    "/config/rag/rrf_top_n": "15",
    "/config/rag/rerank_top_k": "6",
    "/config/rag/compress_budget_tokens": "3000",
    "/config/rag/confidence_threshold": "0.30",
    "/config/rag/memory_ttl_days": "30",
    "/config/rag/history_rounds": "3",
    "/config/rag/web_search_timeout_seconds": "8",
    "/config/rag/rerank_require_call": "true",
    "/config/rag/feature/cache_enabled": "true",
    "/config/rag/feature/web_search_enabled": "true",
    "/config/rag/feature/agent_retrieval_enabled": "true",
}


async def seed() -> None:
    client = get_etcd_client()
    if not await client.health():
        logger.error("etcd 不可达，请先 docker compose up -d")
        sys.exit(1)

    # 1. rag.* 参数（不覆盖已存在值）
    for key, value in DEFAULT_CONFIGS.items():
        if await client.get(key) is None:
            await client.put(key, value)
            logger.info("写入 %s = %s", key, value)

    # 2. 供应商种子
    for name, cfg in BUILTIN_PROVIDERS.items():
        key = f"{PROVIDER_PREFIX}{name}"
        if await client.get(key) is None:
            await client.put(key, cfg.to_json(mask_key=False))
            logger.info("写入供应商 %s", name)

    logger.info("etcd 种子完成")


if __name__ == "__main__":
    asyncio.run(seed())
