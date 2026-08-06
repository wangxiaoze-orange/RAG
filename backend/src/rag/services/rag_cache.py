"""② RagCacheService：问题归一化 → Redis 计数 freq → 高频(≥3)且命中则缓存回放
- freq 键：rag:freq:{normalized}（问题级计数，TTL 30 天）
- 缓存键：rag:cache:{normalized}:{kb_scope_hash}（答案缓存，TTL 7 天可配）
- 防缓存穿透：freq < 阈值时不读不写缓存
"""
import hashlib
import json
import logging

from src.config.config_center import config_center
from src.db.redis import get_redis
from src.utils.text_normalizer import normalize_question

logger = logging.getLogger(__name__)

FREQ_PREFIX = "rag:freq:"
CACHE_PREFIX = "rag:cache:"


def scope_hash(kb_ids: list[int] | None) -> str:
    """知识库范围哈希（缓存键的一部分）"""
    if not kb_ids:
        return "all"
    raw = ",".join(str(k) for k in sorted(set(kb_ids)))
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _cache_key(normalized: str, kb_scope: str) -> str:
    return f"{CACHE_PREFIX}{normalized}:{kb_scope}"


async def incr_freq(normalized: str) -> int:
    """② 标准化问题计数 +1，返回当前 freq（首次 1）"""
    redis = get_redis()
    key = f"{FREQ_PREFIX}{normalized}"
    freq = await redis.incr(key)
    await redis.expire(key, 30 * 86400)  # TTL 30 天
    return freq


async def get_freq(normalized: str) -> int:
    redis = get_redis()
    raw = await redis.get(f"{FREQ_PREFIX}{normalized}")
    return int(raw) if raw else 0


async def get_cache(normalized: str, kb_scope: str) -> dict | None:
    """读取缓存答案 {answer, sources, elapsed_ms, created_at}，无则 None"""
    redis = get_redis()
    raw = await redis.get(_cache_key(normalized, kb_scope))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


async def set_cache(normalized: str, kb_scope: str, data: dict) -> None:
    """写缓存答案（TTL 可配，默认 7 天）"""
    ttl = await config_center.get_int("rag.cache_ttl_seconds", 604800)
    redis = get_redis()
    await redis.set(_cache_key(normalized, kb_scope), json.dumps(data, ensure_ascii=False), ex=ttl)


async def check_cache(normalized: str, kb_scope: str) -> dict | None:
    """② 完整判断：freq 达标且命中缓存才返回缓存（防穿透）"""
    min_freq = await config_center.get_int("rag.cache_freq_threshold", 3)
    freq = await get_freq(normalized)
    if freq < min_freq:
        return None
    return await get_cache(normalized, kb_scope)
