"""① 会话管理：按 conversationId 复用会话，没有则自动创建（标题取问题前20字）
保存用户消息到 qa_message；加载最近 3 轮对话历史到上下文
"""
import datetime
import logging

from sqlalchemy import select

from src.db.models import QaConversation, QaMessage
from src.db.session import async_session_maker
from src.rag.nodes._common import emit_stage
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig

logger = logging.getLogger(__name__)


async def session_node(state: ChatState, config: RunnableConfig) -> dict:
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    sink = ctx.sink
    emit_stage(sink, "session", "创建/复用会话")

    question = state["question"]
    title = question[:20]
    reused = False

    async with async_session_maker() as session:
        conv = None
        if state.get("conversation_id"):
            conv = await session.get(QaConversation, state["conversation_id"])
            if conv is not None and conv.user_id != ctx.user_id:
                conv = None  # 越权 → 重新创建
        if conv is None:
            conv = QaConversation(
                user_id=ctx.user_id,
                title=title,
                provider_id=None,
                model_name=ctx.model,
                kb_ids=ctx.kb_ids or None,
            )
            session.add(conv)
            await session.flush()
        else:
            reused = True

        # 保存用户消息
        msg = QaMessage(
            conversation_id=conv.id,
            user_id=ctx.user_id,
            role="user",
            content=question,
        )
        session.add(msg)
        await session.flush()
        message_id = msg.id

        # 更新会话元信息
        conv.message_count += 1
        conv.last_message_at = datetime.datetime.now(datetime.timezone.utc)
        if ctx.model:
            conv.model_name = ctx.model
        await session.commit()

        # 加载最近 3 轮历史（user+assistant 各 3 条，共 6 条）
        history_rows = (
            await session.execute(
                select(QaMessage)
                .where(QaMessage.conversation_id == conv.id, QaMessage.role.in_(["user", "assistant"]))
                .order_by(QaMessage.id.desc())
                .limit(6)
            )
        ).scalars().all()
        ctx.history = [
            {"role": m.role, "content": m.content}
            for m in sorted(history_rows, key=lambda m: m.id)
        ][:-1]  # 去掉刚存的这条用户消息本身（生成时再拼）

    sink.emit("session", {"conversation_id": conv.id, "message_id": message_id, "reused": reused, "title": title})
    return {
        "conversation_id": conv.id,
        "message_id": message_id,
        "chat_history": ctx.history,
    }
