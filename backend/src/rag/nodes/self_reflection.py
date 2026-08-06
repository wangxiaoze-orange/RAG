"""⑮ 自纠错审查：LLM 对答案做事实一致性/完整性评分
- score ≥ 0.4（可配）→ 通过，保留原答案
- score < 0.4 → 携带审查意见重生成一次（再次流式），并记录 reviewed=True
- 审查调用失败/解析失败 → 保守通过（不阻塞链路）
"""
import logging

from src.config.config_center import config_center
from src.rag.nodes._common import emit_stage, invoke_llm_json, stream_llm
from src.rag.services.prompt_assembler import render_reflection_prompt
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig

logger = logging.getLogger(__name__)

REFLECTION_THRESHOLD = 0.4


async def self_reflection_node(state: ChatState, config: RunnableConfig) -> dict:
    """⑮ 审查答案，必要时重生成一次"""
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "reflect", "自纠错审查")

    question = state["question"]
    answer = state.get("answer") or ""
    references = state.get("references") or []

    threshold = await config_center.get_float("rag.reflection_threshold", REFLECTION_THRESHOLD)
    prompt = render_reflection_prompt(question, answer, references)
    review = await invoke_llm_json(ctx, prompt, system="你是质量审查员，只输出 JSON。")

    if not review:
        # 审查失败 → 保守通过
        return {"reflection": {"conclusion": "pass", "score": 1.0, "issues": [], "action": "none"}}

    try:
        score = float(review.get("score", 1.0))
    except (TypeError, ValueError):
        score = 1.0
    conclusion = review.get("conclusion") or ("pass" if score >= threshold else "fail")
    issues = review.get("issues") or []
    suggestion = review.get("suggestion") or ""

    reflection = {
        "score": round(score, 2),
        "conclusion": conclusion,
        "issues": [str(i) for i in issues][:5],
        "suggestion": str(suggestion)[:500],
        "action": "none",
    }

    # 低分 → 重生成一次（携带审查意见）
    if score < threshold:
        emit_stage(ctx.sink, "reflect", "审查未通过，重生成中")
        retry_prompt = (
            f"请修正以下回答中的问题（仅输出修正后的完整回答）：\n问题：{question}\n"
            f"原回答：{answer}\n审查意见：{'；'.join(reflection['issues']) or '质量偏低，请基于参考资料重答'}\n"
            f"修正建议：{reflection['suggestion'] or '严格依据参考资料作答，不要编造'}"
        )
        try:
            new_answer = await stream_llm(
                ctx,
                [
                    {"role": "system", "content": state.get("system_prompt") or ""},
                    {"role": "user", "content": retry_prompt},
                ],
                ctx.sink,
            )
            if new_answer.strip():
                answer = new_answer
                reflection["action"] = "regenerated"
        except Exception as e:  # noqa: BLE001
            logger.warning("重生成失败，保留原答案: %s", e)

    ctx.sink.emit("review", {"score": score, "conclusion": conclusion, "issues": reflection["issues"], "action": reflection["action"]})
    return {"reflection": reflection, "answer": answer}
