"""节点公共辅助：LLM 流式调用 / JSON 调用 / 阶段事件"""
import json
import logging

from src.rag.state import RequestCtx, SseSink

logger = logging.getLogger(__name__)

STAGE_NAMES = {
    "session": "会话管理",
    "cache": "缓存检查",
    "overview": "知识库概览",
    "memory": "记忆抽取",
    "intent": "意图识别",
    "rewrite": "查询改写",
    "scope": "直读判断",
    "retrieve": "检索召回",
    "fuse": "结果融合",
    "rerank": "语义重排",
    "compress": "上下文压缩",
    "safety": "安全审查",
    "assemble": "Prompt 组装",
    "generate": "流式生成",
    "reflect": "自纠错审查",
    "finish": "收尾",
}


def emit_stage(sink: SseSink, stage: str, detail: str = "") -> None:
    """推 stage 事件（前端思考过程面板）"""
    sink.emit("stage", {"stage": stage, "name": STAGE_NAMES.get(stage, stage), "detail": detail})


def _chunk_delta(chunk) -> str:
    """兼容各版 chunk 形态：字符串内容 / 内容块列表（text block）/ 纯 usage 空块"""
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text") or "")
        return "".join(parts)
    return ""


async def stream_llm(ctx: RequestCtx, messages: list[dict], sink: SseSink | None = None) -> str:
    """⑭ 流式调用 LLM：token 逐段推给前端，返回累计答案"""
    answer = ""
    try:
        async for chunk in ctx.llm.astream(messages):
            delta = _chunk_delta(chunk)
            if delta:
                if sink:
                    sink.emit("token", {"delta": delta})
                answer += delta
    except Exception as e:  # noqa: BLE001
        logger.error("LLM 流式调用失败: %s", e)
        raise
    return answer


async def invoke_llm_json(ctx: RequestCtx, prompt: str, system: str | None = None) -> dict | None:
    """非流式 JSON 调用：解析首个 JSON 对象，失败返回 None"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        resp = await ctx.llm.ainvoke(messages)
        text = (resp.content or "") if isinstance(resp.content, str) else str(resp.content or "")
        return parse_json_loose(text)
    except Exception as e:  # noqa: BLE001
        logger.warning("LLM JSON 调用失败: %s", e)
        return None


def parse_json_loose(text: str) -> dict | None:
    """宽松 JSON 解析：直接解析 → 截取首个 { } 块"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
