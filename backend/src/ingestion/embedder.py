"""批量嵌入：供应商工厂包装（默认硅基流动 BAAI/bge-m3）"""
import logging

from src.providers.base import ProviderConfig
from src.providers.factory import embed_texts

logger = logging.getLogger(__name__)

BATCH_SIZE = 32


async def embed_chunk_texts(provider: ProviderConfig, texts: list[str]) -> list[list[float]]:
    """分批嵌入（失败重试 2 次），返回与 texts 等长的向量列表"""
    vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        for attempt in range(3):
            try:
                vectors.extend(await embed_texts(provider, batch))
                break
            except Exception as e:  # noqa: BLE001
                logger.warning("嵌入失败（第 %d 次）: %s", attempt + 1, e)
                if attempt == 2:
                    raise
    return vectors
