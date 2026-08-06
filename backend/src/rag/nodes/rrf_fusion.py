"""⑨ RRF 融合：recalls 多路列表 → fused_chunks topN
- 标准路径：RRF score = Σ 1/(k + rank)，k=60，按 chunk_id/url 去重
- 直读路径（document_scope）：不走 RRF，用顺序分（scope_chunks 已带 1/(i+1)）
- 单路且不足 RRF 意义时仍走 RRF（保证链路一致）
"""
import logging

from src.config.config_center import config_center
from src.rag.nodes._common import emit_stage
from src.rag.state import ChatState, RunnableConfig

logger = logging.getLogger(__name__)

RRF_K = 60


def _dedup_key(chunk: dict) -> str:
    return chunk.get("chunk_id") or chunk.get("web_url") or chunk.get("content", "")[:64]


async def rrf_fusion_node(state: ChatState, config: RunnableConfig) -> dict:
    """⑨ RRF 融合 top15（可配）"""
    ctx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "fuse", "RRF 多路融合")

    top_n = await config_center.get_int("rag.rrf_top_k", 15)

    # 直读路径：顺序分直出（均匀抽样，无需 RRF）
    if state.get("direct_scope"):
        scope_chunks = sorted(state.get("scope_chunks") or [], key=lambda c: c["score"], reverse=True)
        fused = scope_chunks[:top_n]
        ctx.sink.emit("fuse", {"method": "sequential", "routes": 1, "top": len(fused)})
        # 直读路径跳过 rerank 节点：在此定稿置信度（取最高顺序分），视为检索命中
        return {
            "fused_chunks": fused,
            "retrieval_hit": bool(fused),
            "confidence": round(fused[0]["score"], 4) if fused else 0.0,
        }

    recalls = state.get("recalls") or []
    if not recalls:
        logger.info("RRF 融合: 无任何召回路（工具未返回切片）")
        ctx.sink.emit("fuse", {"method": "none", "routes": 0, "top": 0})
        return {"fused_chunks": [], "retrieval_hit": False}

    scores: dict[str, dict] = {}  # dedup_key → {chunk, score, routes}
    for route in recalls:
        for rank, chunk in enumerate(route):
            key = _dedup_key(chunk)
            entry = scores.setdefault(key, {"chunk": chunk, "score": 0.0, "routes": set()})
            entry["score"] += 1.0 / (RRF_K + rank + 1)
            entry["routes"].add(chunk.get("source_type", "?"))
    for entry in scores.values():
        entry["chunk"]["score"] = round(entry["score"], 6)
        entry["chunk"]["hit_routes"] = sorted(entry["routes"])

    fused = sorted(
        (e["chunk"] for e in scores.values() if e["chunk"].get("content")),
        key=lambda c: c["score"],
        reverse=True,
    )[:top_n]

    hit = bool(fused)
    logger.info("RRF 融合: routes=%d candidates=%d top=%d", len(recalls), len(scores), len(fused))
    ctx.sink.emit("fuse", {
        "method": "rrf",
        "routes": len(recalls),
        "candidates": len(scores),
        "top": len(fused),
    })
    return {"fused_chunks": fused, "retrieval_hit": hit}
