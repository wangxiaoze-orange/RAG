"""分层意图识别（先分层锁定检索范围，再 LLM 多标签意图，最后代码动作匹配）：
- Layer 1（规则，零成本）：关键词锁定 intent_scope（kb/chat/web/mixed/direct/memory）
- Layer 2（LLM，多标签）：按 intent_classify.txt 模板输出 labels/sub_questions/needs_decomposition
- Layer 3（代码，确定性）：策略合并（label→工具权重映射）+ 加权投票（工具命中权重求和定检索策略）
"""
import logging
import re

from src.rag.nodes._common import emit_stage, invoke_llm_json
from src.rag.services.prompt_assembler import render_intent_prompt
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig

logger = logging.getLogger(__name__)

# ============ Layer 1：规则分层 ============
# 网页实时类问题 → web；个性化/记忆类 → memory
WEB_KEYWORDS = ["最新", "今天", "现在", "新闻", "实时", "热搜", "行情", "汇率", "天气", "刚刚", "近期", "最近", "股价"]
MEMORY_KEYWORDS = ["我喜欢", "我不喜欢", "我过敏", "叫我", "记得", "我的习惯", "上次我说", "我的名字"]
# 纯闲聊/寒暄（不检索）
CHAT_PATTERNS = [
    r"^(你好|您好|hi|hello|嗨|哈喽|hey)(!|！|呀|啊|呢)?$",
    r"^(谢谢|多谢|感谢)(你)?(!|！|啦|了)?$",
    r"^(再见|拜拜|bye)(!|！)?$",
    r"^你(是|叫|是谁)?(谁|什么)?$",
    r"^(你是谁|你是干什么的|你能做什么)(!|！|\?|？)?$",
]
SUMMARY_WORDS = ["总结", "概述", "概括", "讲了什么", "介绍", "主要内容", "要点", "摘要", "有哪些内容", "目录"]

# Layer 3 工具权重表（策略合并）：label → 各工具加权投票
LABEL_TOOL_WEIGHTS: dict[str, dict[str, float]] = {
    "need_vector": {"doc_search": 1.0, "keyword_search": 0.3},
    "need_bm25": {"keyword_search": 1.0, "doc_search": 0.3},
    "need_web": {"web_search": 1.0},
    "need_memory": {"recall_memory": 1.0},
    "need_fact_check": {"doc_search": 0.7, "keyword_search": 0.5, "web_search": 0.6},
    "need_summary": {"doc_search": 0.8, "keyword_search": 0.4},
    "need_comparison": {"doc_search": 0.8, "keyword_search": 0.5, "web_search": 0.4},
}
# 默认 label（LLM 失败时按 scope 兜底）
SCOPE_DEFAULT_LABELS = {
    "kb": ["need_vector", "need_bm25"],
    "web": ["need_web"],
    "memory": ["need_memory"],
    "mixed": ["need_vector", "need_bm25", "need_web"],
    "direct": ["need_summary"],
    "chat": [],
}


def layer1_rule_scope(question: str, kb_ids: list[int] | None, direct_scope: bool = False) -> str:
    """Layer 1 规则分层：返回 intent_scope"""
    q = question.strip()
    if direct_scope:
        return "direct"
    if re.search("|".join(CHAT_PATTERNS), q, re.I):
        return "chat"
    has_kb = bool(kb_ids)
    has_web = any(w in q for w in WEB_KEYWORDS)
    has_memory = any(w in q for w in MEMORY_KEYWORDS)
    if not has_kb:
        if has_web:
            return "web"
        if has_memory:
            return "memory"
        if len(q) <= 8:
            return "chat"
        return "web"  # 无知识库 → 全部走网页检索
    if has_memory and has_web:
        return "mixed"
    if has_memory:
        return "kb" if not has_web else "mixed"
    if has_web:
        return "mixed"
    return "kb"


def weighted_vote_tools(labels: list[str]) -> list[str]:
    """Layer 3 加权投票：对每个 label 的权重求和，取权重>0.9 的工具作为检索策略"""
    votes: dict[str, float] = {}
    for label in labels:
        for tool, w in LABEL_TOOL_WEIGHTS.get(label, {}).items():
            votes[tool] = votes.get(tool, 0.0) + w
    if not votes:
        return []
    top = max(votes.values())
    return [t for t, v in sorted(votes.items(), key=lambda kv: -kv[1]) if v >= max(0.9, top * 0.6)]


async def intent_node(state: ChatState, config: RunnableConfig) -> dict:
    """分层意图识别主节点（③ 概览短路之后、④ 改写之前执行）"""
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "intent", "分层意图识别")
    question = state["question"]

    # Layer 1：规则锁定检索范围（零成本，先于 LLM）
    scope = layer1_rule_scope(question, ctx.kb_ids, state.get("direct_scope", False))
    labels: list[str] = []
    sub_questions: list[str] = []
    needs_decomposition = False

    # Layer 2：LLM 多标签意图（chat/direct 无需调用，省一次 LLM 往返）
    if scope not in ("chat", "direct"):
        result = await invoke_llm_json(ctx, render_intent_prompt(question), system="你是意图识别器，只输出 JSON。")
        if result:
            labels = result.get("labels") or []
            if isinstance(labels, str):
                labels = [labels]
            labels = [l for l in labels if l in LABEL_TOOL_WEIGHTS]
            needs_decomposition = bool(result.get("needs_decomposition"))
            raw_subs = result.get("sub_questions") or []
            sub_questions = [str(s) for s in raw_subs if str(s).strip()][:3]
            logger.info("LLM 意图: scope=%s labels=%s 拆解=%s", scope, labels, needs_decomposition)
        if not labels:
            labels = list(SCOPE_DEFAULT_LABELS.get(scope, []))

    # Layer 3：策略合并 + 加权投票 → 最终检索工具策略
    tools = weighted_vote_tools(labels)

    ctx.sink.emit("intent", {
        "scope": scope,
        "labels": labels,
        "sub_questions": sub_questions,
        "needs_decomposition": needs_decomposition,
        "tools": tools,
    })
    return {
        "intent_scope": scope,
        "intent_labels": labels,
        "sub_questions": sub_questions,
        "needs_decomposition": needs_decomposition,
    }
