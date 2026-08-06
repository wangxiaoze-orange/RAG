"""⑩ Cross-Encoder 重排：调供应商 /rerank 端点（OpenAI 兼容重排 API）
硅基流动默认模型 BAAI/bge-reranker-v2-m3；候选不足也调用——目的是拿到真实语义分数
"""
import logging

import httpx

from src.providers.base import ProviderConfig

logger = logging.getLogger(__name__)


async def rerank(
    provider: ProviderConfig,
    query: str,
    chunks: list[dict],
    top_n: int = 6,
) -> list[dict]:
    """对候选切片重排，返回按 relevance_score 降序的 top_n 列表
    未配置 rerank_model 或调用失败时抛异常（调用方降级为融合分数）
    """
    if not provider.rerank_model:
        raise RuntimeError(f"供应商 {provider.name} 未配置 rerank_model")
    if not chunks:
        return []

    documents = [c["content"][:2000] for c in chunks]  # 截断防超限
    headers = {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}
    url = f"{provider.base_url.rstrip('/')}/rerank"
    payload = {"model": provider.rerank_model, "query": query, "documents": documents, "top_n": min(top_n, len(documents))}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    # 兼容 results=[{index,relevance_score}] 两种命名（relevance_score / score）
    results = data.get("results") or data.get("data") or []
    scored = []
    for item in results:
        idx = item.get("index")
        score = item.get("relevance_score", item.get("score", 0.0))
        if idx is None or idx >= len(chunks):
            continue
        chunk = dict(chunks[idx])
        chunk["score"] = round(float(score), 4)
        chunk["source_type"] = chunk.get("source_type", "rerank")
        scored.append(chunk)
    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored[:top_n]
