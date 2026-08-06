"""⑩ 语义重排：硅基流动 bge-reranker-v2-m3（供应商 rerank_model，可配）
- 候选不足 top_n 也调用——目的是拿到真实语义分数供置信度判断
- 调用失败 → 降级用融合分数（保持链路健壮），confidence 取最高分
- confidence 与 retrieval_hit 在此定稿（⑫ SafetyGuard 消费）
"""
import logging

from src.config.config_center import config_center
from src.rag.nodes._common import emit_stage
from src.rag.services.reranker import rerank as rerank_service
from src.rag.services.safety import judge_retrieval_hit
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig

logger = logging.getLogger(__name__)

DEFAULT_CONFIDENCE_THRESHOLD = 0.20


async def rerank_node(state: ChatState, config: RunnableConfig) -> dict:
    """⑩ 重排 fused_chunks → reranked_chunks + confidence + retrieval_hit"""
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "rerank", "语义重排")

    top_n = await config_center.get_int("rag.rerank_top_n", 6)
    threshold = await config_center.get_float("rag.confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD)
    fused = state.get("fused_chunks") or []
    query = state.get("rewritten_query") or state["question"]

    reranked: list[dict] = []
    degraded = False  # 重排不可用时降级为融合分（秩分，量纲≠语义分数）
    if fused:
        try:
            reranked = await rerank_service(ctx.provider, query, fused, top_n=top_n)
        except Exception as e:  # noqa: BLE001
            logger.warning("重排服务不可用，降级融合分数: %s", e)
            degraded = True
            reranked = sorted(fused, key=lambda c: c.get("score", 0), reverse=True)[:top_n]

    if not fused:
        logger.info("重排候选为空：工具召回 0 条（检查 kb_ids=%s 过滤范围与工具返回）", ctx.kb_ids)

    confidence = round(reranked[0]["score"], 4) if reranked else 0.0
    if degraded:
        # 降级分是 RRF 秩分（≈1/(60+rank) 累加，量级 0.01~0.05），不能与语义阈值直接比较，
        # 否则永远判「未命中」→ 检索成功也走常识兜底。有真实候选即视为命中（0.01 兜底下限）
        retrieval_hit = bool(reranked) and confidence >= 0.01
    else:
        retrieval_hit = judge_retrieval_hit(confidence, threshold)

    # 决定性日志：下次复现时直接看到候选数 / 置信度 / 实际阈值 / 判定结果
    logger.info(
        "重排定稿: 候选=%d top=%d confidence=%.4f threshold=%.2f retrieval_hit=%s degraded=%s",
        len(fused), len(reranked), confidence, threshold, retrieval_hit, degraded,
    )

    ctx.sink.emit("rerank", {
        "candidates": len(fused),
        "top": len(reranked),
        "confidence": confidence,
        "threshold": threshold,
        "retrieval_hit": retrieval_hit,
        "degraded": degraded,  # 前端/日志可区分：降级判定 vs 语义判定
    })
    return {
        "reranked_chunks": reranked,
        "confidence": confidence,
        "retrieval_hit": retrieval_hit,
    }
