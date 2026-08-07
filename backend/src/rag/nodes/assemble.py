"""⑬ Prompt 组装：角色 + 用户画像 + 长期记忆 + 参考来源[1][2][3] + 历史 3 轮 + 问题
- 直读路径用 scope_chunks 作参考来源；标准路径用压缩后上下文
- 用户画像从长期记忆中的 name/style 类型记忆构建
"""
import logging

from src.rag.nodes._common import emit_stage
from src.rag.services.parent_expand import expand_parents
from src.rag.services.prompt_assembler import build_history_text, render_knowledge_system
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig

logger = logging.getLogger(__name__)

# 记忆类型 → 画像描述（v1 仅用这两类）
PROFILE_TYPES = {"name": "称呼", "style": "回答风格"}


async def assemble_node(state: ChatState, config: RunnableConfig) -> dict:
    """⑬ 组装系统提示与参考来源"""
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "assemble", "Prompt 组装")

    # 参考来源：直读路径用抽样切片，标准路径用压缩上下文（直读路径也需父块扩展）
    references = state.get("compressed_context")
    if not references:
        references = await expand_parents(state.get("scope_chunks") or [])

    # 用户画像（从记忆构建）
    profile_parts = []
    for m in state.get("memories") or []:
        label = PROFILE_TYPES.get(m.get("type"))
        if label and m.get("content"):
            profile_parts.append(f"{label}：{m['content']}")
    user_profile = "；".join(profile_parts)

    history_text = build_history_text(ctx.history)
    system_prompt = render_knowledge_system(
        user_profile=user_profile,
        memories=state.get("memories"),
        references=references,
        history=history_text,
    )

    ctx.sink.emit("assemble", {"references": len(references), "profile": bool(user_profile)})
    return {"system_prompt": system_prompt, "references": references}
