"""③ 知识库概览短路：正则识别概览问题 → 不走检索，直接查真实文档清单喂 LLM 流式作答
原因：这类问题向量检索匹配不到，会误触发兜底或让 LLM 编造不存在的内容
"""
import logging
import re

from sqlalchemy import select

from src.db.models import KbKnowledgeBase
from src.db.session import async_session_maker
from src.rag.nodes._common import emit_stage, stream_llm
from src.rag.services.prompt_assembler import render_overview_system
from src.rag.state import ChatState, RunnableConfig, RequestCtx, RunnableConfig

logger = logging.getLogger(__name__)

# 概览正则： "知识库"+概览词 或 "有哪些/列出"+文档词
OVERVIEW_RE = re.compile(
    r"(知识库.{0,10}(有什么|有哪些|包含|内容|介绍|概览|目录|清单))"
    r"|((有哪些|列出|看看|都有|介绍一下).{0,8}(文档|资料|知识库))"
    r"|^(我的)?知识库(里|中)?(有|包括|有哪些)?(什么|哪些|啥)"
)


def is_overview_question(question: str) -> bool:
    return bool(OVERVIEW_RE.search(question.strip()))


async def overview_detect_node(state: ChatState, config: RunnableConfig) -> dict:
    """概览问题检测（路由分支判断）"""
    return {"is_overview": is_overview_question(state["question"])}


async def overview_answer_node(state: ChatState, config: RunnableConfig) -> dict:
    """概览作答：查 kb_knowledge_base 真实清单 → LLM 流式作答 → 收尾"""
    ctx: RequestCtx = config["configurable"]["request_ctx"]
    emit_stage(ctx.sink, "overview", "读取真实文档清单")

    # 查真实文档清单（名称/描述/文档数/切片数）
    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(KbKnowledgeBase).where(KbKnowledgeBase.owner_id == ctx.user_id)
            )
        ).scalars().all()
    docs = [
        {
            "name": r.name,
            "description": r.description,
            "doc_count": r.doc_count,
            "chunk_count": r.chunk_count,
        }
        for r in rows
    ]

    # 喂给 LLM 流式作答（只引用真实数据，不允许编造）
    system = render_overview_system(docs)
    answer = await stream_llm(
        ctx,
        [{"role": "system", "content": system}, {"role": "user", "content": state["question"]}],
        ctx.sink,
    )
    return {
        "overview_docs": docs,
        "path_type": "overview",
        "answer": answer,
        "sources": [],
        "references": [],
        "retrieval_hit": True,
        "use_fallback": False,
    }
