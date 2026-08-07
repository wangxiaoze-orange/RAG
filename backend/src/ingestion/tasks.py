"""入库任务编排：parse → clean → chunk → embed → 写 Milvus + MySQL → 更新状态
默认 uvicorn 进程内后台执行；.env 设 INGESTION_MODE=arq 时投递 Redis 队列由独立 worker 消费
"""
import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import select, update

from src.config.settings import settings

try:
    from arq.connections import RedisSettings
    _HAS_ARQ = True
except ImportError:  # arq 未安装：恒走 in-process，不影响主功能
    _HAS_ARQ = False

from src.core.minio_client import get_minio
from src.utils.text_normalizer import estimate_tokens
from src.db.models import KbChunk, KbDocument, KbKnowledgeBase
from src.db.session import async_session_maker
from src.ingestion.chunker import chunk_fixed, chunk_markdown, chunk_parent_child
from src.ingestion.cleaner import clean_text
from src.ingestion.embedder import embed_chunk_texts
from src.ingestion.parser import parse_document
from src.ingestion.semantic_chunker import chunk_semantic
from src.providers.manager import provider_manager
from src.rag.services.vector_store import get_vector_store

logger = logging.getLogger(__name__)

CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
PARENT_CHILD_SIZE = 256   # 父子策略子块默认尺寸


async def _set_status(doc_id: int, status: str, error_msg: str | None = None) -> None:
    async with async_session_maker() as session:
        await session.execute(
            update(KbDocument)
            .where(KbDocument.id == doc_id)
            .values(status=status, error_msg=error_msg)
        )
        await session.commit()


async def process_document(ctx: Any, doc_id: int) -> dict:
    """入库管线主任务（arq 签名：第一个参数为任务上下文，in-process 调用时传 None）"""
    start_summary: dict = {"doc_id": doc_id, "status": "failed"}

    # 1. 读取文档记录 + 知识库入库配置
    async with async_session_maker() as session:
        doc = await session.get(KbDocument, doc_id)
        if doc is None:
            return {**start_summary, "error": "文档不存在"}
        kb_id, filename, minio_object = doc.kb_id, doc.filename, doc.minio_object
        kb = await session.get(KbKnowledgeBase, kb_id)

    strategy = (kb.chunk_strategy if kb else None) or "markdown"
    chunk_size = (kb.chunk_size if kb else None) or CHUNK_SIZE
    chunk_overlap = (kb.chunk_overlap if kb else None) or CHUNK_OVERLAP
    parse_pref = (kb.parse_pref if kb else None) or "auto"
    parse_min_conf = float(kb.parse_min_confidence) if kb and kb.parse_min_confidence is not None else 0.5

    try:
        # 2. 解析（指定解析器 + 置信度过滤）
        await _set_status(doc_id, "parsing")
        data = await get_minio().get_bytes(minio_object)
        markdown, parser, parse_confidence = parse_document(
            filename, data, prefer=parse_pref, min_confidence=parse_min_conf
        )
        logger.info("文档 %d 解析完成（%s，置信度=%s）", doc_id, parser, parse_confidence)

        # 3. 清洗
        await _set_status(doc_id, "cleaning")
        cleaned = clean_text(markdown)

        # 4. 嵌入供应商（语义切分也需要，提前拿）
        provider = await provider_manager.get_default()
        if provider is None or not provider.embedding_model:
            raise RuntimeError("未配置带嵌入模型的供应商（请在前端供应商页配置 embedding_model）")

        # 5. 分块（按知识库策略）
        await _set_status(doc_id, "chunking")
        parents: list[dict] = []
        if strategy == "fixed":
            chunks = chunk_fixed(cleaned, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        elif strategy == "semantic":
            try:
                chunks = await chunk_semantic(
                    cleaned,
                    embed_many=lambda texts: embed_chunk_texts(provider, texts),
                    chunk_size=chunk_size,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("语义切分失败，降级固定切分: %s", e)
                chunks = chunk_fixed(cleaned, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        elif strategy == "parent_child":
            chunks, parents = chunk_parent_child(cleaned, child_size=PARENT_CHILD_SIZE, child_overlap=min(chunk_overlap, 80))
        else:  # markdown（默认，标题感知）
            chunks = chunk_markdown(cleaned, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        if not chunks:
            raise ValueError("分块结果为空")

        # 6. 嵌入（仅子块/普通块，父块不参与向量检索）
        await _set_status(doc_id, "embedding")
        vectors = await embed_chunk_texts(provider, [c["content"] for c in chunks])

        # 7. 写 Milvus + MySQL（父子策略：先落父块拿 id，再回填子块 parent_id）
        await _set_status(doc_id, "embedding")
        vector_store = get_vector_store()
        await vector_store.ensure_collection()
        milvus_rows = [
            {
                "chunk_id": f"{doc_id}_{i}",
                "doc_id": doc_id,
                "kb_id": kb_id,
                "doc_name": filename,
                "page_number": None,  # MinerU 行级页码映射为 v2 增强点
                "section_title": c.get("section_title") or "",
                "content": c["content"],
                "embedding": vectors[i],
            }
            for i, c in enumerate(chunks)
        ]
        await vector_store.insert_chunks(milvus_rows)

        async with async_session_maker() as session:
            # 父块先落库（is_parent=1，不参与检索）
            parent_db_ids: dict[int, int] = {}
            for p in parents:
                prow = KbChunk(
                    kb_id=kb_id,
                    doc_id=doc_id,
                    doc_name=filename,
                    chunk_index=-(p["index"] + 1),  # 负数索引区分父块
                    content=p["content"],
                    token_count=estimate_tokens(p["content"]),
                    is_parent=1,
                    embedding_provider=provider.name,
                )
                session.add(prow)
                await session.flush()
                parent_db_ids[p["index"]] = prow.id
            for i, c in enumerate(chunks):
                session.add(
                    KbChunk(
                        kb_id=kb_id,
                        doc_id=doc_id,
                        doc_name=filename,
                        chunk_index=c["chunk_index"],
                        content=c["content"],
                        token_count=c["token_count"],
                        page_number=None,
                        section_title=c.get("section_title"),
                        heading_path=c.get("heading_path"),
                        milvus_id=None,
                        embedding_provider=provider.name,
                        parent_id=parent_db_ids.get(c.get("parent_index")) if parents else None,
                    )
                )
            await session.commit()

        # 8. 收尾：更新文档与知识库计数
        async with async_session_maker() as session:
            await session.execute(
                update(KbDocument)
                .where(KbDocument.id == doc_id)
                .values(
                    status="ready",
                    chunk_count=len(chunks),
                    parse_pipeline=parser,
                    parse_confidence=parse_confidence,
                    error_msg=None,
                )
            )
            kb = await session.get(KbKnowledgeBase, kb_id)
            if kb:
                docs = (
                    await session.execute(
                        select(KbDocument).where(KbDocument.kb_id == kb_id, KbDocument.status == "ready")
                    )
                ).scalars().all()
                chunk_total = (
                    await session.execute(
                        select(KbChunk.id).where(KbChunk.kb_id == kb_id)
                    )
                ).scalars().all()
                kb.doc_count = len(docs)
                kb.chunk_count = len(chunk_total)
            await session.commit()

        logger.info("文档 %d 入库完成：%d 片（策略=%s，父块=%d）", doc_id, len(chunks), strategy, len(parents))
        return {"doc_id": doc_id, "status": "ready", "chunk_count": len(chunks), "parser": parser}

    except Exception as e:  # noqa: BLE001
        logger.exception("文档 %d 入库失败", doc_id)
        await _set_status(doc_id, "failed", str(e)[:500])
        return {**start_summary, "error": str(e)}


async def delete_document(doc_id: int) -> None:
    """删除文档：Milvus 按 doc_id 删 + MySQL 行删 + MinIO 对象删 + 计数更新"""
    async with async_session_maker() as session:
        doc = await session.get(KbDocument, doc_id)
        if doc is None:
            return
        kb_id, minio_object, md_object = doc.kb_id, doc.minio_object, doc.md_object

    await get_vector_store().delete_by_doc(doc_id)

    async with async_session_maker() as session:
        from sqlalchemy import delete as sa_delete
        await session.execute(sa_delete(KbChunk).where(KbChunk.doc_id == doc_id))
        await session.execute(sa_delete(KbDocument).where(KbDocument.id == doc_id))
        kb = await session.get(KbKnowledgeBase, kb_id)
        if kb:
            docs = (
                await session.execute(
                    select(KbDocument).where(KbDocument.kb_id == kb_id, KbDocument.status == "ready")
                )
            ).scalars().all()
            chunk_total = (
                await session.execute(
                    select(KbChunk.id).where(KbChunk.kb_id == kb_id)
                )
            ).scalars().all()
            kb.doc_count = len(docs)
            kb.chunk_count = len(chunk_total)
        await session.commit()

    await get_minio().remove(minio_object)
    if md_object:
        await get_minio().remove(md_object)
    logger.info("文档 %d 已删除", doc_id)


async def enqueue_or_run(doc_id: int) -> str:
    """入库投递：默认 uvicorn 进程内后台解析（不依赖额外进程，部署即用）；
    .env 设 INGESTION_MODE=arq 时改投 Redis 队列，需另行启动 arq worker 消费"""
    if settings.ingestion_mode == "arq" and _HAS_ARQ:
        try:
            from arq.connections import create_pool
            pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            try:
                await pool.enqueue_job("process_document", doc_id)
                return "queued"
            finally:
                await pool.aclose()
        except Exception as e:  # noqa: BLE001
            logger.warning("arq 投递失败，回退 in-process 入库: %s", e)
    asyncio.create_task(process_document(None, doc_id))
    return "inline"


if _HAS_ARQ:

    class WorkerSettings:
        """arq worker 配置（需在 .env 设 INGESTION_MODE=arq 时使用）：
        启动：`arq src.ingestion.tasks.WorkerSettings`（独立进程）"""
        functions = [process_document]
        redis_settings = RedisSettings.from_dsn(settings.redis_url)
        max_jobs = 4
        job_timeout = 3600  # 单文档入库最长 1 小时
