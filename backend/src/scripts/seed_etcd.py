"""etcd 配置种子（可选）：与 deploy/etcd/seed-config.sh 等价的手动版
用于 docker-compose 之外手动搭建中间件时执行（如 Windows 本机直跑 etcd）
用法：python -m src.scripts.seed_etcd
"""
import asyncio
import logging

from src.config.config_center import config_center
from src.config.etcd_client import get_etcd_client

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

DEFAULT_CONFIG = {
    "rag.cache_freq_threshold": "3",
    "rag.cache_write_min_freq": "3",
    "rag.cache_ttl_seconds": "604800",
    "rag.document_scope_chunk_budget": "18",
    "rag.rrf_top_k": "15",
    "rag.rerank_top_n": "6",
    "rag.compress_budget_tokens": "3000",
    "rag.confidence_threshold": "0.20",
    "rag.reflection_threshold": "0.4",
    "rag.memory_ttl_days": "30",
    "rag.web_search_timeout_seconds": "8",
    "rag.feature.cache_enabled": "true",
    "rag.feature.web_search_enabled": "true",
    "rag.feature.agent_retrieval_enabled": "true",
}


async def main() -> None:
    client = get_etcd_client()
    ok = await client.health()
    if not ok:
        logger.error("etcd 不可达（%s），请先启动中间件", "settings.etcd_endpoints")
        return
    # 已存在的不覆盖（与 seed-config.sh 的 put_config 语义一致）
    for key, value in DEFAULT_CONFIG.items():
        current = await config_center.get_raw(key)
        if current is None:
            await client.put(config_center._etcd_key(key), value)
            logger.info("写入 %s = %s", key, value)
        else:
            logger.info("跳过（已存在）%s = %s", key, current)
    logger.info("etcd 种子完成 ✅")


if __name__ == "__main__":
    asyncio.run(main())
