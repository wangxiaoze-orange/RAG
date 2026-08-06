"""⑭ LLM 流式生成：系统提示 + 用户问题 → SSE token 流
- 紧急词命中 → 答案尾部追加紧急提示（⑫ SafetyGuard 消费）
"""
import logging

from src.rag.nodes._common import emit_stage, stream_llm
from src.rag.services.safety import EMERGENCY_TIP
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig

logger = logging.getLogger(__name__)


async def generate_node(state: ChatState, config: RunnableConfig) -> dict:
    """⑭ 流式生成（standard / document_scope 路径）"""
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "generate", "流式生成")

    system_prompt = state.get("system_prompt")
    if not system_prompt:
        raise RuntimeError("generate_node: 缺少 system_prompt（assemble 未执行）")

    answer = await stream_llm(
        ctx,
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": state["question"]}],
        ctx.sink,
    )

    # 紧急提示追加（只在未包含时追加一次）
    flags = state.get("safety_flags") or []
    if flags and EMERGENCY_TIP not in answer:
        answer += EMERGENCY_TIP
        ctx.sink.emit("safety", {"emergency_tip_appended": True, "flags": flags})

    # path_type 保持上游（document_scope 等），缺省才是 standard
    return {"answer": answer, "path_type": state.get("path_type") or "standard"}
