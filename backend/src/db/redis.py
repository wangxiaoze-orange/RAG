"""Redis 异步客户端单例（缓存/计数/用户记忆共用）"""
import redis.asyncio as aioredis

from src.config.settings import settings

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis
