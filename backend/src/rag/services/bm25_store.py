"""BM25 关键词检索：进程内 rank_bm25 + jieba 中文分词
语料从 MySQL kb_chunk 按需加载（按 kb_ids 组合缓存，TTL 5 分钟）
"""
import asyncio
import logging
import time
from functools import lru_cache

import jieba
from rank_bm25 import BM25Okapi
from sqlalchemy import select

from src.db.models import KbChunk
from src.db.session import async_session_maker

logger = logging.getLogger(__name__)

_CORPUS_TTL = 300.0  # 语料缓存 5 分钟


def _tokenize(text: str) -> list[str]:
    """中文分词：jieba 精确模式"""
    return [t for t in jieba.lcut(text) if t.strip()]


class BM25Store:
    def __init__(self) -> None:
        self._corpus_cache: dict[tuple, tuple[float, BM25Okapi, list[dict]]] = {}

    async def _load_corpus(self, kb_ids: list[int] | None) -> tuple[BM25Okapi, list[dict]]:
        """从 MySQL 加载切片语料（带缓存）"""
        key = tuple(sorted(kb_ids)) if kb_ids else ("all",)
        cached = self._corpus_cache.get(key)
        if cached and time.monotonic() - cached[0] < _CORPUS_TTL:
            return cached[1], cached[2]

        async with async_session_maker() as session:
            stmt = select(KbChunk.id, KbChunk.kb_id, KbChunk.doc_id, KbChunk.doc_name,
                          KbChunk.content, KbChunk.page_number, KbChunk.section_title)
            if kb_ids:
                stmt = stmt.where(KbChunk.kb_id.in_(kb_ids))
            rows = (await session.execute(stmt)).all()

        corpus = [r.content for r in rows]
        model = BM25Okapi([_tokenize(c) for c in corpus]) if corpus else None
        meta = [
            {
                "chunk_id": r.id,
                "kb_id": r.kb_id,
                "doc_id": r.doc_id,
                "doc_name": r.doc_name,
                "content": r.content,
                "page_number": r.page_number,
                "section_title": r.section_title,
            }
            for r in rows
        ]
        self._corpus_cache[key] = (time.monotonic(), model, meta)
        return model, meta

    async def search(
        self,
        query: str,
        kb_ids: list[int] | None = None,
        top_k: int = 10,
    ) -> list[dict]:
        """BM25 检索，返回按分数降序"""
        if not query.strip():
            return []
        model, meta = await self._load_corpus(kb_ids)
        if model is None:
            return []
        scores = model.get_scores(_tokenize(query))
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out = []
        for rank, idx in enumerate(ranked[:top_k], start=1):
            item = dict(meta[idx])
            item["score"] = round(float(scores[idx]), 4)
            item["source_type"] = "bm25"
            item["rank"] = rank
            out.append(item)
        return out


@lru_cache(maxsize=1)
def get_bm25_store() -> BM25Store:
    return BM25Store()
