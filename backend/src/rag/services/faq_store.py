"""高频问题经验库（FAQ）存取：
- match_faq：归一化问题精确匹配已发布且未过期的经验条目（范围兼容：请求 kb_ids ⊆ 条目 kb_ids）
- settle_faq：高频且检索命中的答案自动沉淀为待审核条目（同问题不重复沉淀）
"""
import datetime
import logging

from sqlalchemy import select

from src.db.models import QaFaq
from src.db.session import async_session_maker

logger = logging.getLogger(__name__)


def _scope_ok(faq_kb_ids: list | None, request_kb_ids: list[int] | None) -> bool:
    """请求的知识库范围必须是条目适用范围的子集（条目 kb_ids 为空=全局经验）"""
    if not faq_kb_ids:
        return True
    req = set(request_kb_ids or [])
    return req.issubset(set(faq_kb_ids))


async def match_faq(normalized: str, kb_ids: list[int] | None) -> dict | None:
    """精确匹配已发布、未过期且范围兼容的经验条目；命中则自增 hit_count"""
    if not normalized:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(QaFaq).where(
                    QaFaq.question_normalized == normalized,
                    QaFaq.status == "published",
                )
            )
        ).scalars().all()
        for row in rows:
            if row.expire_at is not None:
                expire = row.expire_at if row.expire_at.tzinfo else row.expire_at.replace(tzinfo=datetime.timezone.utc)
                if expire <= now:
                    continue
            if not _scope_ok(row.kb_ids, kb_ids):
                continue
            row.hit_count = (row.hit_count or 0) + 1
            await session.commit()
            logger.info("FAQ 命中: id=%d q=%s", row.id, normalized[:60])
            return {
                "faq_id": row.id,
                "answer": row.answer,
                "sources": row.sources or [],
                "elapsed_ms": 0,
            }
    return None


async def settle_faq(
    *,
    question: str,
    normalized: str,
    rewritten: str | None,
    answer: str,
    sources: list[dict] | None,
    kb_ids: list[int] | None,
    freq: int,
) -> int | None:
    """自动沉淀为待审核经验；同归一化问题已存在记录则跳过，返回新记录 id"""
    if not normalized or not answer:
        return None
    async with async_session_maker() as session:
        exists = (
            await session.execute(
                select(QaFaq.id).where(QaFaq.question_normalized == normalized).limit(1)
            )
        ).scalars().first()
        if exists:
            return None
        row = QaFaq(
            question=question[:512],
            question_normalized=normalized[:512],
            rewritten_question=(rewritten or "")[:512] or None,
            answer=answer,
            sources=sources or None,
            kb_ids=kb_ids or None,
            status="pending",
            freq=freq,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        logger.info("FAQ 自动沉淀: id=%d freq=%d q=%s", row.id, freq, normalized[:60])
        return row.id
