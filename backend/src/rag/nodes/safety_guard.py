"""⑫ SafetyGuard + 常识兜底：
- 紧急词命中 → safety_flags（生成后追加紧急提示）
- 检索未命中（confidence < 阈值）→ knowledge_fallback_node 常识兜底作答，
  系统提示明确告知"基于通用知识"，避免编造知识库内容
"""
import logging

from src.rag.nodes._common import emit_stage, stream_llm
from src.rag.services.prompt_assembler import render_fallback_system
from src.rag.services.safety import check_emergency
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig

logger = logging.getLogger(__name__)


async def safety_guard_node(state: ChatState, config: RunnableConfig) -> dict:
    """⑫ 安全审查：紧急词检测（生成节点消费 safety_flags）"""
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "safety", "安全审查")

    flags = check_emergency(state["question"])
    ctx.sink.emit("safety", {
        "emergency": flags,
        "confidence": state.get("confidence"),
        "retrieval_hit": state.get("retrieval_hit", False),
    })
    return {"safety_flags": flags}


async def knowledge_fallback_node(state: ChatState, config: RunnableConfig) -> dict:
    """⑫ 常识兜底：检索未命中时明确告知基于通用知识作答"""
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "safety", "未检索到相关内容 → 常识兜底")

    system = render_fallback_system()
    question = state["question"]
    answer = await stream_llm(
        ctx,
        [{"role": "system", "content": system}, {"role": "user", "content": question}],
        ctx.sink,
    )
    return {
        "answer": answer,
        "path_type": "fallback",
        "use_fallback": True,
        "retrieval_hit": False,
        "references": [],
        "sources": [],
    }
