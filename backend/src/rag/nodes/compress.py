"""⑪ 上下文压缩：重排结果按 token 预算裁剪（默认 3000），单块上限 2000 字符
防止长文档把 Prompt 撑爆，保住高质量片段
"""
import logging

from src.config.config_center import config_center
from src.rag.nodes._common import emit_stage
from src.rag.services.compressor import compress
from src.rag.services.parent_expand import expand_parents
from src.rag.state import ChatState, RunnableConfig

logger = logging.getLogger(__name__)


async def compress_node(state: ChatState, config: RunnableConfig) -> dict:
    ctx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "compress", "上下文压缩")

    budget = await config_center.get_int("rag.compress_budget_tokens", 3000)
    chunks = await expand_parents(state.get("reranked_chunks") or [])
    compressed = await compress(chunks, budget_tokens=budget)

    ctx.sink.emit("compress", {"input": len(chunks), "kept": len(compressed), "budget_tokens": budget})
    return {"compressed_context": compressed}
