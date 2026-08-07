"""⑬ PromptAssembler：角色设定 + 用户画像 + 长期记忆 + 参考来源[1][2][3] + 对话历史 + 用户问题
从 templates/*.txt 读取系统模板，按需渲染
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _load_template(name: str) -> str:
    path = _PROMPTS_DIR / name
    return path.read_text(encoding="utf-8")


def _render_references(chunks: list[dict]) -> str:
    """渲染参考来源 [1][2][3]，带文档名/章节/页码标注 + 切片正文
    正文必须拼进去：模型只能读到这里的内容，只有标题它就会说「知识库中未找到相关信息」
    """
    if not chunks:
        return "（无）"
    lines = []
    for i, c in enumerate(chunks, start=1):
        doc = c.get("doc_name") or c.get("filename") or "未知文档"
        page = c.get("page_number")
        section = c.get("section_title")
        loc = " | ".join(x for x in (section and f"第{section}节" or None, page and f"第{page}页" or None) if x)
        suffix = f"（{loc}）" if loc else ""
        content = (c.get("content") or "").strip()
        if content:
            lines.append(f"[{i}]《{doc}》{suffix}\n{content}")
        else:
            lines.append(f"[{i}]《{doc}》{suffix}")
    return "\n\n".join(lines)


def render_knowledge_system(
    *,
    user_profile: str = "",
    memories: list[dict] | None = None,
    references: list[dict] | None = None,
    history: str = "（无）",
) -> str:
    """⑬ 组装知识问答系统提示（主模板）"""
    tmpl = _load_template("knowledge_qa.txt")
    mem_lines = "\n".join(f"- {m.get('content')}" for m in (memories or [])) or "（无）"
    return tmpl.format(
        user_profile=user_profile or "（未提供）",
        memories=mem_lines,
        references=_render_references(references or []),
        history=history,
        question="",  # 问题由调用方以 user 消息追加
    )


def render_fallback_system(references: list[dict] | None = None) -> str:
    """⑫ 常识兜底系统提示（明确告知基于通用知识）"""
    tmpl = _load_template("fallback.txt")
    return tmpl.format(
        references=_render_references(references or []),
        question="",  # 问题由调用方以 user 消息追加
    )


def render_overview_system(overview_docs: list[dict]) -> str:
    """③ 知识库概览系统提示"""
    tmpl = _load_template("overview.txt")
    lines = []
    for kb in overview_docs:
        lines.append(f"- 知识库【{kb.get('name')}】（{kb.get('description') or '无描述'}）：文档 {kb.get('doc_count', 0)} 个，切片 {kb.get('chunk_count', 0)} 片")
    return tmpl.format(overview_docs="\n".join(lines) or "（暂无知识库）")


def render_rewrite_prompt(question: str, history: str = "") -> str:
    """④ 查询改写提示"""
    return _load_template("rewrite.txt").format(question=question, history=history or "（无）")


def render_intent_prompt(question: str) -> str:
    """分层意图识别（第二层 LLM 多标签）提示"""
    return _load_template("intent_classify.txt").format(question=question)


def render_agent_system(intent_hint: str = "", sub_questions: list[str] | None = None, budget_hint: str = "") -> str:
    """⑦ ReAct 代理系统提示（含意图提示、拆解子问题与召回配额）"""
    return _load_template("agent_system.txt").format(
        intent_hint=intent_hint or "（无）",
        sub_questions="\n".join(f"- {q}" for q in (sub_questions or [])) or "（无）",
        budget_hint=budget_hint or "（无限制，默认各工具 10 条）",
    )


def render_reflection_prompt(question: str, answer: str, references: list[dict] | None = None) -> str:
    """⑮ 自纠错审查提示"""
    return _load_template("reflection.txt").format(
        question=question,
        answer=answer,
        references=_render_references(references or []),
    )


def build_history_text(history: list[dict]) -> str:
    """把最近 N 轮对话历史渲染成文本（供模板）"""
    lines = []
    for msg in history[-6:]:  # 最近 3 轮
        role = "用户" if msg.get("role") == "user" else "助手"
        content = (msg.get("content") or "").strip()
        if content:
            lines.append(f"{role}：{content[:200]}")
    return "\n".join(lines) or "（无）"
