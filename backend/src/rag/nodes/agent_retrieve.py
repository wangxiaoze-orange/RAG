"""⑦ 检索主路径（ReAct Agent）：
- create_react_agent(ctx.llm, 4 工具)，系统提示含意图提示 + 子问题
- 工具调用经 tool_logger 逐条推 SSE tool_call 事件并落 tool_logs（推理链）
- collector 收集各工具真实召回 → tool_results（⑧ 多路召回合并）
- 异常/零召回 → retrieval_failed=True，图条件边降级到规则路由
"""
import logging
import time

from langchain_core.prompts import ChatPromptTemplate
from langgraph.prebuilt import create_react_agent

from src.config.config_center import config_center
from src.rag.nodes._common import emit_stage
from src.rag.services.prompt_assembler import render_agent_system
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig
from src.rag.tools.rag_toolkit import build_langchain_tools

logger = logging.getLogger(__name__)

MAX_AGENT_STEPS = 6  # 防失控：最多 6 步工具循环


async def agent_retrieve_node(state: ChatState, config: RunnableConfig) -> dict:
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "retrieve", "LLM 智能检索（ReAct）")

    enabled = await config_center.get_bool("rag.feature.agent_retrieval_enabled", True)
    if not enabled:
        # 特性关闭 → 直接走规则路由降级路径（图条件边会判定）
        return {"retrieval_failed": True, "retrieval_source": "router"}

    tool_logs: list[dict] = []
    collector: dict[str, list] = {}

    def tool_logger(entry: dict) -> None:
        tool_logs.append(entry)
        # 实时推给前端思考过程面板
        ctx.sink.emit("tool_call", {"name": entry["tool"], "args": entry.get("args"), "summary": entry.get("summary")})

    tools = build_langchain_tools(
        kb_ids=ctx.kb_ids,
        user_id=ctx.user_id,
        embed_fn=ctx.embed_fn,
        tool_logger=tool_logger,
        collector=collector,
        budgets=state.get("recall_budgets") or None,
    )
    intent_hint = "、".join(state.get("intent_labels") or [])
    budgets = state.get("recall_budgets") or {}
    budget_hint = "、".join(f"{t}≤{n} 条" for t, n in budgets.items()) if budgets else ""
    system = render_agent_system(
        intent_hint=intent_hint,
        sub_questions=state.get("sub_questions") or [],
        budget_hint=budget_hint,
    )
    start = time.monotonic()
    agent_trace: list[dict] = []
    try:
        # langgraph 1.x：messages_modifier 已重命名为 prompt（创建失败同样降级规则路由，不崩流水线）
        agent = create_react_agent(
            ctx.llm,
            tools,
            prompt=ChatPromptTemplate.from_messages([
                ("system", system),
                ("placeholder", "{messages}"),
            ]),
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": state.get("rewritten_query") or state["question"]}]},
            config={"recursion_limit": MAX_AGENT_STEPS * 4},
        )
        # 推理链：agent 内部消息（含 tool_calls / tool 结果）
        for m in result.get("messages", []):
            if getattr(m, "type", "") in ("ai", "tool"):
                agent_trace.append({
                    "role": m.type,
                    "content": str(m.content)[:500] if m.content else None,
                    "tool_calls": getattr(m, "tool_calls", None) or None,
                })
    except Exception as e:  # noqa: BLE001
        logger.warning("ReAct 检索异常，降级规则路由: %s", e)
        return {
            "tool_results": dict(collector),
            "tool_logs": tool_logs,
            "agent_trace": agent_trace,
            "retrieval_failed": True,
            "retrieval_source": "router",
        }

    latency_ms = int((time.monotonic() - start) * 1000)
    hit_total = sum(len(v) for v in collector.values())
    logger.info(
        "ReAct 检索完成: 工具调用 %d 次, 各工具命中 %s, 合计 %d",
        len(tool_logs), {k: len(v) for k, v in collector.items()}, hit_total,
    )
    # 零召回（没调任何工具 / 全空）→ 降级规则路由
    retrieval_failed = hit_total == 0
    ctx.sink.emit("retrieve", {
        "source": "agent",
        "tool_calls": len(tool_logs),
        "hits": hit_total,
        "latency_ms": latency_ms,
        "failed": retrieval_failed,
    })
    return {
        "tool_results": dict(collector),
        "tool_logs": tool_logs,
        "agent_trace": agent_trace,
        "retrieval_failed": retrieval_failed,
        "retrieval_source": "agent" if not retrieval_failed else "router",
    }
