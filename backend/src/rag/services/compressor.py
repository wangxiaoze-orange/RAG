"""⑪ ContextCompressor：按 token 预算裁剪参考上下文（保高分、截长文）"""
import logging

from src.utils.text_normalizer import estimate_tokens

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 2000  # 单切片截断上限（防超长切片撑爆预算）


async def compress(chunks: list[dict], budget_tokens: int = 3000) -> list[dict]:
    """按分数降序裁剪切片至预算内；单切片超长则截断"""
    if not chunks:
        return []
    ordered = sorted(chunks, key=lambda c: c.get("score", 0.0), reverse=True)
    out: list[dict] = []
    used = 0
    for chunk in ordered:
        content = chunk["content"]
        if len(content) > MAX_CHUNK_CHARS:
            content = content[:MAX_CHUNK_CHARS] + "…（截断）"
            chunk = dict(chunk)
            chunk["content"] = content
        tokens = estimate_tokens(content)
        if used + tokens > budget_tokens and out:
            break  # 预算耗尽（至少保留一条）
        out.append(chunk)
        used += tokens
    logger.info("上下文压缩：%d 条 → %d 条（%d token）", len(chunks), len(out), used)
    return out
