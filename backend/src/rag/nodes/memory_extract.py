"""⑥ 显式记忆抽取：正则匹配"我喜欢X/我不喜欢X/我对X过敏/请用X回答/叫我X"
→ 写入用户记忆（Redis，30天可配）；同时把既有记忆载入状态（⑬ Prompt 组装用）
"""
import logging

from src.config.config_center import config_center
from src.rag.nodes._common import emit_stage
from src.rag.services import user_memory
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig

logger = logging.getLogger(__name__)


async def memory_extract_node(state: ChatState, config: RunnableConfig) -> dict:
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "memory", "显式记忆抽取")

    # 抽取并保存本次新记忆
    saved = await user_memory.save_explicit_from_question(ctx.user_id, state["question"])
    if saved:
        ttl_days = await config_center.get_int("rag.memory_ttl_days", 30)
        ctx.sink.emit("memory", {"saved": saved, "expire_days": ttl_days})
        logger.info("用户 %d 新增记忆 %d 条", ctx.user_id, len(saved))

    # 载入既有记忆（供 recall_memory 工具与 Prompt 组装）
    memories = await user_memory.list_memories(ctx.user_id)
    return {"new_memories": saved, "memories": memories}
