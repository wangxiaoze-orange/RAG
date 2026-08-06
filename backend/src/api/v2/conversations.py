"""会话 API：列表 / 历史消息 / 删除"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_current_user, get_db
from src.db.models import QaConversation, QaMessage
from src.schemas.kb import ConversationOut, MessageOut

router = APIRouter(prefix="/api/v2/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ConversationOut]:
    rows = (
        await db.execute(
            select(QaConversation)
            .where(QaConversation.user_id == user["user_id"])
            # MySQL 的 DESC 排序 NULL 天然排最后，无需 nulls_last()（那是 PG 语法）
            .order_by(QaConversation.last_message_at.desc(), QaConversation.id.desc())
        )
    ).scalars().all()
    return [ConversationOut.model_validate(r) for r in rows]


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    conv = await db.get(QaConversation, conversation_id)
    if conv is None or conv.user_id != user["user_id"]:
        raise HTTPException(status_code=404, detail="会话不存在")
    rows = (
        await db.execute(
            select(QaMessage).where(QaMessage.conversation_id == conversation_id).order_by(QaMessage.id)
        )
    ).scalars().all()
    return [MessageOut.model_validate(r) for r in rows]


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conv = await db.get(QaConversation, conversation_id)
    if conv is None or conv.user_id != user["user_id"]:
        raise HTTPException(status_code=404, detail="会话不存在")
    from sqlalchemy import delete as sa_delete
    await db.execute(sa_delete(QaMessage).where(QaMessage.conversation_id == conversation_id))
    await db.delete(conv)
    await db.commit()
    return {"ok": True}
