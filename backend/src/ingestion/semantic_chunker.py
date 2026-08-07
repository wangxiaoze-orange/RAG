"""语义切分：按句切分 → 句向量 → 相邻句相似度跌破分位阈值处分段
嵌入不可用或句数过少时抛 ValueError，由调用方降级 fixed 策略
"""
import logging
import math
import re
from typing import Awaitable, Callable

from src.utils.text_normalizer import estimate_tokens

logger = logging.getLogger(__name__)

# 中英文句界（保留标点在前句末尾）
SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?；;\n])")
BREAK_PERCENTILE = 70  # 相似度跌破该分位 → 断句


def _split_sentences(text: str) -> list[str]:
    parts = SENT_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * p / 100))
    return ordered[idx]


async def chunk_semantic(
    text: str,
    embed_many: Callable[[list[str]], Awaitable[list[list[float]]]],
    chunk_size: int = 512,
) -> list[dict]:
    """语义分块，返回 [{chunk_index, content, section_title, heading_path, token_count}]"""
    sentences = _split_sentences(text)
    if len(sentences) < 4:
        raise ValueError("句数过少，无需语义切分")

    vectors = await embed_many(sentences)
    if len(vectors) != len(sentences):
        raise ValueError("嵌入结果与句数不一致")

    sims = [_cosine(vectors[i], vectors[i + 1]) for i in range(len(sentences) - 1)]
    threshold = _percentile(sims, BREAK_PERCENTILE)

    # 相似度低于阈值处分段，再按 chunk_size 累积合并
    groups: list[list[str]] = [[]]
    for i, sent in enumerate(sentences):
        groups[-1].append(sent)
        if i < len(sims) and sims[i] < threshold:
            groups.append([])

    chunks: list[dict] = []
    buf = ""
    for group in groups:
        # 中文句子自带标点，直接拼接
        piece = "".join(group)
        if not piece.strip():
            continue
        if buf and len(buf) + len(piece) > chunk_size:
            chunks.append(buf.strip())
            buf = piece
        else:
            buf += piece
    if buf.strip():
        chunks.append(buf.strip())

    out = [
        {
            "content": c,
            "section_title": None,
            "heading_path": None,
            "token_count": estimate_tokens(c),
        }
        for c in chunks
    ]
    for idx, c in enumerate(out):
        c["chunk_index"] = idx
    logger.info("语义切分完成：%d 句 → %d 片（相似度阈值 %.3f）", len(sentences), len(out), threshold)
    return out
