"""④ 查询改写：结合历史上下文把口语化/指代性问题改写为检索友好提问
- chat/直读路径不改写（无需检索语义）
- LLM 改写失败或结果异常 → 回退原问题（保证链路健壮）
"""
import logging

from src.rag.nodes._common import emit_stage
from src.rag.services.prompt_assembler import build_history_text, render_rewrite_prompt
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig

logger = logging.getLogger(__name__)

MAX_REWRITE_LEN = 200


async def rewrite_node(state: ChatState, config: RunnableConfig) -> dict:
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "rewrite", "查询改写")

    question = state["question"]
    scope = state.get("intent_scope", "kb")

    # 闲聊/直读不改写：改写无意义且浪费 LLM 往返
    if scope in ("chat", "direct"):
        return {"rewritten_query": question}

    history_text = build_history_text(ctx.history[-4:])  # 最近 2 轮
    prompt = render_rewrite_prompt(question, history_text)
    rewritten = question
    try:
        resp = await ctx.llm.ainvoke([{"role": "user", "content": prompt}])
        text = (resp.content or "").strip() if isinstance(resp.content, str) else str(resp.content or "").strip()
        text = text.strip("。. ")
        if text and len(text) <= MAX_REWRITE_LEN and question[:8] not in text:
            rewritten = text
    except Exception as e:  # noqa: BLE001
        logger.warning("查询改写失败，回退原问题: %s", e)

    changed = rewritten != question
    ctx.sink.emit("rewrite", {"original": question, "rewritten": rewritten, "changed": changed})
    return {"rewritten_query": rewritten}
