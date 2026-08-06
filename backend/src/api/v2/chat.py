"""聊天流式 API：POST /api/v2/chat/stream（SSE Named Events）
事件协议：session / stage / tool_call / token / cache_hit / memory / intent / rewrite / review / error / done
实现：LangGraph 在后台任务中运行，事件经 asyncio.Queue 汇到 StreamingResponse 逐条下发
"""
import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.core.deps import get_current_user, get_provider_manager
from src.core.sse import sse_format
from src.providers.factory import create_chat_llm, create_embeddings
from src.providers.manager import ProviderManager
from src.rag.graph import get_graph
from src.rag.state import RequestCtx, SseSink

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/chat", tags=["chat"])

PING_INTERVAL = 15  # 空闲心跳秒


class ChatStreamRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000, description="用户问题")
    conversation_id: int | None = None
    kb_ids: list[int] | None = None
    provider_name: str | None = None
    model: str | None = None


@router.post("/stream")
async def chat_stream(
    body: ChatStreamRequest,
    user: dict = Depends(get_current_user),
    provider_manager: ProviderManager = Depends(get_provider_manager),
) -> StreamingResponse:
    """SSE 流式问答（完整 16 步流水线）"""
    # 供应商解析：显式指定 > 全局默认；无可用供应商直接 400
    if body.provider_name:
        provider = await provider_manager.get(body.provider_name)
        if provider is None:
            raise HTTPException(status_code=400, detail=f"供应商 {body.provider_name} 不存在")
    else:
        provider = await provider_manager.get_default()
        if provider is None:
            raise HTTPException(status_code=400, detail="尚未配置任何模型供应商，请先在前端供应商页配置并设为默认")

    llm = create_chat_llm(provider, model=body.model)
    embed_fn = None
    if provider.embedding_model:
        embeddings = create_embeddings(provider)
        embed_fn = lambda q: asyncio.to_thread(embeddings.embed_query, q)  # noqa: E731 同步方法 → 线程池

    sink = SseSink()
    ctx = RequestCtx(
        sink=sink,
        user_id=user["user_id"],
        username=user["username"],
        kb_ids=body.kb_ids or [],
        provider_name=provider.name,
        model=body.model or provider.model,
        provider=provider,
        llm=llm,
        embed_fn=embed_fn,
    )
    initial_state = {
        "user_id": ctx.user_id,
        "username": ctx.username,
        "conversation_id": body.conversation_id,
        "question": body.question,
        "kb_ids": ctx.kb_ids,
        "provider_name": provider.name,
        "model": ctx.model,
        "start_time": time.monotonic(),
    }
    logger.info(
        "聊天请求: user=%s kb_ids=%s provider=%s model=%s question=%s",
        user["username"], body.kb_ids or [], provider.name, ctx.model, body.question[:80],
    )

    async def event_gen():
        graph_task = asyncio.create_task(get_graph().ainvoke(initial_state, {"configurable": {"request_ctx": ctx}}))
        pending_get = None
        try:
            while True:
                pending_get = asyncio.ensure_future(sink.queue.get())
                done, _ = await asyncio.wait(
                    {pending_get, graph_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if graph_task in done:
                    # 图结束：pending_get 可能已从队列取走一条（最早的未消费事件），先补发它再排空，保证事件顺序不丢
                    if pending_get.done() and not pending_get.cancelled():
                        item = pending_get.result()
                        if item is not None:
                            yield sse_format(*item)
                    while not sink.queue.empty():
                        item = sink.queue.get_nowait()
                        if item is None:
                            break
                        yield sse_format(*item)
                    try:
                        await graph_task
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:  # noqa: BLE001
                        logger.exception("流水线执行失败")
                        yield sse_format("error", {"code": "pipeline_error", "message": str(e)[:500]})
                    break
                item = pending_get.result()  # 事件先到
                if item is None:
                    break
                yield sse_format(*item)
        except asyncio.CancelledError:
            # 客户端断开：取消后台图任务，避免悬挂
            graph_task.cancel()
            logger.info("SSE 客户端断开，取消流水线")
            raise

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 关 nginx 缓冲，保证逐 token 下发
        },
    )
