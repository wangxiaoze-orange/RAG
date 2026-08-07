"""LangGraph 状态定义 + 请求上下文（SSE 事件汇/供应商/嵌入函数注入）"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, TypedDict

# LangGraph 1.2+ 要求节点 config 参数注解为 RunnableConfig（否则不注入 → TypeError），
# 统一从 state 模块 re-export，节点文件只 import state
from langchain_core.runnables import RunnableConfig  # noqa: F401


class ChatState(TypedDict, total=False):
    """聊天流水线共享状态（①-⑯ 各节点读写）"""

    # 基础信息
    user_id: int
    username: str
    conversation_id: int | None
    message_id: int | None          # 用户消息持久化后的 id
    question: str
    kb_ids: list[int]
    provider_name: str
    model: str | None
    start_time: float
    chat_history: list[dict]        # 最近 3 轮 [{role, content}]

    # ② 缓存
    normalized_question: str
    freq: int
    cache_hit: bool
    cached_answer: dict | None      # {answer, sources, elapsed_ms}
    faq_hit: bool                   # 命中经验库（FAQ）直读
    faq_id: int | None

    # ③ 概览短路
    is_overview: bool
    overview_docs: list[dict]

    # ④ 改写
    rewritten_query: str

    # 意图（分层）
    intent_scope: str               # kb/chat/web/mixed/direct
    intent_labels: list[str]        # need_vector/need_bm25/need_web/need_memory
    label_confidences: dict         # {label: confidence} 每标签置信度
    recall_budgets: dict            # {tool: top_k} 置信度加权后的各工具召回配额
    sub_questions: list[str]
    needs_decomposition: bool

    # ⑤ 文档直读
    direct_scope: bool
    scope_chunks: list[dict]

    # ⑥ 记忆
    memories: list[dict]
    new_memories: list[dict]

    # ⑦ 检索
    tool_results: dict              # {tool_name: [chunks]}
    recalls: list[list[dict]]       # ⑧ merge 输出：多路召回（⑨ RRF 输入）——未声明会被 LangGraph 丢弃
    retrieval_failed: bool          # ReAct 异常 → 降级标志
    retrieval_source: str           # agent/router
    tool_logs: list[dict]           # [{tool, args, summary, latency_ms}]
    agent_trace: list[dict]         # 推理链

    # ⑧⑨⑩⑪
    fused_chunks: list[dict]
    reranked_chunks: list[dict]
    confidence: float
    retrieval_hit: bool
    compressed_context: list[dict]

    # ⑫
    safety_flags: list[str]
    use_fallback: bool

    # ⑬⑭⑮⑯
    system_prompt: str              # ⑬ assemble 输出（⑭ generate 消费）——同样必须声明
    references: list[dict]
    answer: str
    reflection: dict
    sources: list[dict]
    path_type: str                  # standard/overview/document_scope/cache_replay/fallback
    cache_written: bool
    assistant_message_id: int | None
    error: str | None


class SseSink:
    """SSE 事件汇：节点内同步 emit，SSE 端点异步消费"""

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()

    def emit(self, event: str, data: dict) -> None:
        self.queue.put_nowait((event, data))

    async def close(self) -> None:
        await self.queue.put(None)  # 结束哨兵


@dataclass
class RequestCtx:
    """单请求上下文（经 graph config.configurable 注入节点）：
    供应商客户端 / 嵌入函数 / SSE 事件汇 / 配置中心
    """
    sink: SseSink
    user_id: int
    username: str
    kb_ids: list[int]
    provider_name: str
    model: str | None
    provider: Any                     # ProviderConfig
    llm: Any                          # langchain_openai.ChatOpenAI（1.x async-first）
    embed_fn: Callable[[str], list[float]] | None
    history: list[dict] = field(default_factory=list)
