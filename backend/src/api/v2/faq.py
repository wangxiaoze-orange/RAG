"""高频问题经验库（FAQ）API：
- 管理员：列表/搜索（按状态与关键词）/编辑答案与有效期/发布/停用/删除
- 普通用户：GET /faqs/search?q= 搜库中已发布问题（直接读经验，不走检索）
"""
import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_current_user, get_db, require_admin
from src.db.models import QaFaq

router = APIRouter(prefix="/api/v2/faqs", tags=["faq"])


class FaqOut(BaseModel):
    id: int
    question: str
    question_normalized: str
    rewritten_question: str | None = None
    answer: str
    sources: list | None = None
    kb_ids: list | None = None
    status: str
    freq: int = 1
    hit_count: int = 0
    expire_at: datetime.datetime | None = None
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class FaqUpdate(BaseModel):
    question: str | None = Field(default=None, max_length=512)
    rewritten_question: str | None = Field(default=None, max_length=512)
    answer: str | None = None
    expire_at: datetime.datetime | None = None
    kb_ids: list[int] | None = None


def _not_expired(row: QaFaq) -> bool:
    if row.expire_at is None:
        return True
    expire = row.expire_at if row.expire_at.tzinfo else row.expire_at.replace(tzinfo=datetime.timezone.utc)
    return expire > datetime.datetime.now(datetime.timezone.utc)


# ============ 管理员 ============
@router.get("", response_model=list[FaqOut])
async def list_faqs(
    status: str = Query(default="all", description="pending/published/disabled/all"),
    q: str = Query(default="", description="问题/答案关键词"),
    limit: int = Query(default=50, le=200),
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[FaqOut]:
    stmt = select(QaFaq).order_by(QaFaq.id.desc()).limit(limit)
    if status != "all":
        stmt = stmt.where(QaFaq.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(QaFaq.question.like(like), QaFaq.rewritten_question.like(like), QaFaq.answer.like(like))
        )
    rows = (await db.execute(stmt)).scalars().all()
    return [FaqOut.model_validate(r) for r in rows]


@router.put("/{faq_id}", response_model=FaqOut)
async def update_faq(
    faq_id: int,
    body: FaqUpdate,
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FaqOut:
    row = await db.get(QaFaq, faq_id)
    if row is None:
        raise HTTPException(status_code=404, detail="经验条目不存在")
    if body.question is not None:
        row.question = body.question
    if body.rewritten_question is not None:
        row.rewritten_question = body.rewritten_question
    if body.answer is not None:
        row.answer = body.answer
    if body.expire_at is not None:
        row.expire_at = body.expire_at
    if body.kb_ids is not None:
        row.kb_ids = body.kb_ids or None
    row.created_by = admin["user_id"]
    await db.commit()
    await db.refresh(row)
    return FaqOut.model_validate(row)


@router.post("/{faq_id}/publish", response_model=FaqOut)
async def publish_faq(
    faq_id: int, admin: dict = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> FaqOut:
    row = await db.get(QaFaq, faq_id)
    if row is None:
        raise HTTPException(status_code=404, detail="经验条目不存在")
    if not row.answer or not row.answer.strip():
        raise HTTPException(status_code=400, detail="答案为空，不能发布")
    row.status = "published"
    row.created_by = admin["user_id"]
    await db.commit()
    await db.refresh(row)
    return FaqOut.model_validate(row)


@router.post("/{faq_id}/disable")
async def disable_faq(
    faq_id: int, admin: dict = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    row = await db.get(QaFaq, faq_id)
    if row is None:
        raise HTTPException(status_code=404, detail="经验条目不存在")
    row.status = "disabled"
    await db.commit()
    return {"ok": True}


@router.delete("/{faq_id}")
async def delete_faq(
    faq_id: int, admin: dict = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    row = await db.get(QaFaq, faq_id)
    if row is None:
        raise HTTPException(status_code=404, detail="经验条目不存在")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ============ 普通用户：搜库 ============
@router.get("/search", response_model=list[FaqOut])
async def search_faqs(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(default=20, le=100),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FaqOut]:
    """搜索已发布且未过期的经验问题（用户直读答案，无需检索）"""
    like = f"%{q}%"
    rows = (
        await db.execute(
            select(QaFaq)
            .where(
                QaFaq.status == "published",
                or_(QaFaq.question.like(like), QaFaq.rewritten_question.like(like), QaFaq.answer.like(like)),
            )
            .order_by(QaFaq.hit_count.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [FaqOut.model_validate(r) for r in rows if _not_expired(r)]
