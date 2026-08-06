"""② 缓存检查（RagCacheService）：问题归一化 → Redis 计数 freq → freq≥3 且命中 → 缓存回放
路由：cache_hit=True → cache_replay_node（跳过后续全部检索生成）；否则继续
"""
import asyncio
import logging

from src.config.config_center import config_center
from src.rag.nodes._common import emit_stage
from src.rag.services import rag_cache
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig
from src.utils.text_normalizer import normalize_question

logger = logging.getLogger(__name__)

REPLAY_CHUNK_CHARS = 12   # 回放时每段模拟流式的字符数
REPLAY_DELAY = 0.02       # 每段间隔秒


async def cache_check_node(state: ChatState, config: RunnableConfig) -> dict:
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "cache", "问题归一化 + 频率计数")

    # 特征开关：关闭后走全链路（灰度开关）
    enabled = await config_center.get_bool("rag.feature.cache_enabled", True)
    if not enabled:
        normalized = normalize_question(state["question"])
        return {"normalized_question": normalized, "cache_hit": False, "freq": 0, "cached_answer": None}

    normalized = normalize_question(state["question"])
    freq = await rag_cache.incr_freq(normalized)
    kb_scope = rag_cache.scope_hash(state.get("kb_ids"))
    cached = await rag_cache.check_cache(normalized, kb_scope)  # 内部含 freq≥3 防穿透判断
    cache_hit = cached is not None
    if cache_hit:
        logger.info("缓存命中：freq=%d", freq)
    return {
        "normalized_question": normalized,
        "freq": freq,
        "cache_hit": cache_hit,
        "cached_answer": cached,
    }


async def cache_replay_node(state: ChatState, config: RunnableConfig) -> dict:
    """② 缓存命中：分块模拟流式回放缓存答案，全程跳过检索/生成"""
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    cached = state["cached_answer"] or {}
    answer = cached.get("answer", "")
    ctx.sink.emit("cache_hit", {"cached": True, "freq": state.get("freq", 0), "replay": True})

    # 分块模拟流式回放
    for i in range(0, len(answer), REPLAY_CHUNK_CHARS):
        ctx.sink.emit("token", {"delta": answer[i : i + REPLAY_CHUNK_CHARS]})
        await asyncio.sleep(REPLAY_DELAY)

    return {
        "path_type": "cache_replay",
        "answer": answer,
        "sources": cached.get("sources", []),
        "references": [],
        "confidence": None,
        "retrieval_hit": True,
        "cache_hit": True,
        "use_fallback": False,
    }
