"""知识库 API：KB CRUD / 文档上传与状态 / 切片预览"""
import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.core.deps import get_current_user, get_db
from src.core.minio_client import get_minio
from src.db.models import KbChunk, KbDocument, KbKnowledgeBase
from src.ingestion.tasks import delete_document, enqueue_or_run
from src.schemas.kb import ChunkOut, DocumentOut, KbCreate, KbOut, KbUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["knowledge-base"])


def _ensure_owner(kb: KbKnowledgeBase | None, user: dict) -> None:
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if kb.owner_id != user["user_id"]:
        raise HTTPException(status_code=403, detail="无权操作该知识库")


# ============ 知识库 CRUD ============
@router.get("/kb", response_model=list[KbOut])
async def list_kb(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[KbOut]:
    rows = (
        await db.execute(
            select(KbKnowledgeBase).where(KbKnowledgeBase.owner_id == user["user_id"]).order_by(KbKnowledgeBase.id.desc())
        )
    ).scalars().all()
    return [KbOut.model_validate(r) for r in rows]


@router.post("/kb", response_model=KbOut)
async def create_kb(
    body: KbCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KbOut:
    kb = KbKnowledgeBase(name=body.name, description=body.description, owner_id=user["user_id"])
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return KbOut.model_validate(kb)


@router.put("/kb/{kb_id}", response_model=KbOut)
async def update_kb(
    kb_id: int,
    body: KbUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KbOut:
    kb = await db.get(KbKnowledgeBase, kb_id)
    _ensure_owner(kb, user)
    if body.name is not None:
        kb.name = body.name
    if body.description is not None:
        kb.description = body.description
    if body.status is not None:
        kb.status = body.status
    await db.commit()
    await db.refresh(kb)
    return KbOut.model_validate(kb)


@router.delete("/kb/{kb_id}")
async def delete_kb(
    kb_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    kb = await db.get(KbKnowledgeBase, kb_id)
    _ensure_owner(kb, user)
    docs = (await db.execute(select(KbDocument).where(KbDocument.kb_id == kb_id))).scalars().all()
    for doc in docs:
        await delete_document(doc.id)
    await db.delete(kb)
    await db.commit()
    return {"ok": True}


# ============ 文档管理 ============
@router.get("/kb/{kb_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    kb_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentOut]:
    kb = await db.get(KbKnowledgeBase, kb_id)
    _ensure_owner(kb, user)
    rows = (
        await db.execute(
            select(KbDocument).where(KbDocument.kb_id == kb_id).order_by(KbDocument.id.desc())
        )
    ).scalars().all()
    return [DocumentOut.model_validate(r) for r in rows]


@router.post("/kb/{kb_id}/documents", response_model=DocumentOut)
async def upload_document(
    kb_id: int,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentOut:
    """上传文档：md5 去重 → MinIO 存原文件 → 建记录 → 投递入库任务"""
    kb = await db.get(KbKnowledgeBase, kb_id)
    _ensure_owner(kb, user)

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="空文件")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"文件超过 {settings.max_upload_mb}MB 限制")

    md5_hex = hashlib.md5(data).hexdigest()
    duplicate = (
        await db.execute(
            select(KbDocument).where(KbDocument.md5 == md5_hex, KbDocument.kb_id == kb_id)
        )
    ).scalars().first()
    if duplicate:
        raise HTTPException(status_code=409, detail=f"文件已存在（{duplicate.filename}），跳过重复入库")

    filename = file.filename or "unnamed"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    object_name = f"kb_{kb_id}/{uuid.uuid4().hex}.{ext}"
    try:
        await get_minio().put_bytes(object_name, data, content_type=file.content_type or "application/octet-stream")
    except Exception as e:  # noqa: BLE001
        logger.exception("MinIO 存储失败: %s", e)
        raise HTTPException(status_code=500, detail=f"对象存储写入失败: {e}") from e

    doc = KbDocument(
        kb_id=kb_id,
        filename=filename,
        file_type=ext,
        size_bytes=len(data),
        md5=md5_hex,
        minio_object=object_name,
        status="uploaded",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # 投递入库（arq 优先，失败 in-process）；投递失败标记 failed 以便重试
    try:
        queue_mode = await enqueue_or_run(doc.id)
    except Exception as e:  # noqa: BLE001
        logger.exception("文档 %d 投递失败: %s", doc.id, e)
        doc.status = "failed"
        doc.error_msg = f"入库任务投递失败: {e}"[:512]
        await db.commit()
        raise HTTPException(status_code=500, detail=doc.error_msg) from e
    logger.info("文档 %d 已投递入库（%s）", doc.id, queue_mode)
    return DocumentOut.model_validate(doc)


@router.delete("/documents/{doc_id}")
async def remove_document(
    doc_id: int,
    user: dict = Depends(get_current_user),
    _db: AsyncSession = Depends(get_db),
) -> dict:
    await delete_document(doc_id)
    return {"ok": True}


@router.post("/documents/{doc_id}/retry")
async def retry_document(
    doc_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    doc = await db.get(KbDocument, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.status != "failed":
        raise HTTPException(status_code=400, detail="仅失败状态的文档可重试")
    doc.status = "uploaded"
    doc.error_msg = None
    await db.commit()
    mode = await enqueue_or_run(doc.id)
    return {"ok": True, "queue": mode}


# ============ 切片预览（⑤直读数据源核对用） ============
@router.get("/kb/{kb_id}/chunks", response_model=list[ChunkOut])
async def list_chunks(
    kb_id: int,
    doc_id: int | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChunkOut]:
    kb = await db.get(KbKnowledgeBase, kb_id)
    _ensure_owner(kb, user)
    stmt = select(KbChunk).where(KbChunk.kb_id == kb_id)
    if doc_id:
        stmt = stmt.where(KbChunk.doc_id == doc_id)
    stmt = stmt.order_by(KbChunk.doc_id, KbChunk.chunk_index).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [ChunkOut.model_validate(r) for r in rows]
