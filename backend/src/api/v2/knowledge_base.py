"""知识库 API：KB CRUD / 文档上传与状态 / 切片预览 / 部门授权
权限模型：
- admin 可见全部知识库；普通用户 = 自己创建的 + 所在部门被授权的
- 文档上传/删除/重试：kb owner 或 admin
- 部门授权管理：仅 admin
"""
import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.core.deps import get_current_user, get_db, require_admin
from src.core.minio_client import get_minio
from src.db.models import Department, KbChunk, KbDepartment, KbDocument, KbKnowledgeBase
from src.ingestion.tasks import delete_document, enqueue_or_run
from src.schemas.kb import (
    ChunkOut,
    DocumentOut,
    KbCreate,
    KbDepartmentsIn,
    KbOut,
    KbUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["knowledge-base"])


# ============ 权限工具 ============
async def visible_kb_ids(db: AsyncSession, user: dict) -> list[int] | None:
    """当前用户可见的知识库 id 列表；admin 返回 None 表示不限制"""
    if user.get("role") == "admin":
        return None
    stmt = select(KbKnowledgeBase.id).where(KbKnowledgeBase.owner_id == user["user_id"])
    own = {(await db.execute(stmt)).scalars().all()}
    granted: set = set()
    if user.get("department_id"):
        rows = (
            await db.execute(
                select(KbDepartment.kb_id).where(KbDepartment.department_id == user["department_id"])
            )
        ).scalars().all()
        granted = set(rows)
    return sorted(own | granted)


async def _dept_names(db: AsyncSession, kb_id: int) -> list[str]:
    rows = (
        await db.execute(
            select(Department.name)
            .join(KbDepartment, KbDepartment.department_id == Department.id)
            .where(KbDepartment.kb_id == kb_id)
        )
    ).scalars().all()
    return list(rows)


async def _kb_out(db: AsyncSession, kb: KbKnowledgeBase, user: dict) -> KbOut:
    out = KbOut.model_validate(kb)
    out.is_owner = kb.owner_id == user["user_id"]
    out.department_names = await _dept_names(db, kb.id)
    return out


def _ensure_visible(kb: KbKnowledgeBase | None, user: dict, allowed_ids: list[int] | None) -> KbKnowledgeBase:
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if allowed_ids is not None and kb.id not in allowed_ids:
        raise HTTPException(status_code=403, detail="无权访问该知识库")
    return kb


def _ensure_can_write(kb: KbKnowledgeBase | None, user: dict) -> None:
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if kb.owner_id != user["user_id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权操作该知识库")


# ============ 知识库 CRUD ============
@router.get("/kb", response_model=list[KbOut])
async def list_kb(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[KbOut]:
    allowed = await visible_kb_ids(db, user)
    stmt = select(KbKnowledgeBase).order_by(KbKnowledgeBase.id.desc())
    if allowed is not None:
        stmt = stmt.where(KbKnowledgeBase.id.in_(allowed or [0]))
    rows = (await db.execute(stmt)).scalars().all()
    return [await _kb_out(db, r, user) for r in rows]


@router.post("/kb", response_model=KbOut)
async def create_kb(
    body: KbCreate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KbOut:
    kb = KbKnowledgeBase(
        name=body.name,
        description=body.description,
        owner_id=user["user_id"],
        chunk_strategy=body.chunk_strategy,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        parse_pref=body.parse_pref,
        parse_min_confidence=body.parse_min_confidence,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return await _kb_out(db, kb, user)


@router.put("/kb/{kb_id}", response_model=KbOut)
async def update_kb(
    kb_id: int,
    body: KbUpdate,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KbOut:
    kb = await db.get(KbKnowledgeBase, kb_id)
    _ensure_can_write(kb, user)
    for field in ("name", "description", "status", "chunk_strategy", "chunk_size", "chunk_overlap", "parse_pref", "parse_min_confidence"):
        value = getattr(body, field)
        if value is not None:
            setattr(kb, field, value)
    await db.commit()
    await db.refresh(kb)
    return await _kb_out(db, kb, user)


@router.delete("/kb/{kb_id}")
async def delete_kb(
    kb_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    kb = await db.get(KbKnowledgeBase, kb_id)
    _ensure_can_write(kb, user)
    docs = (await db.execute(select(KbDocument).where(KbDocument.kb_id == kb_id))).scalars().all()
    for doc in docs:
        await delete_document(doc.id)
    await db.execute(sa_delete(KbDepartment).where(KbDepartment.kb_id == kb_id))
    await db.delete(kb)
    await db.commit()
    return {"ok": True}


# ============ 部门授权（admin） ============
@router.get("/kb/{kb_id}/departments")
async def get_kb_departments(
    kb_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    kb = await db.get(KbKnowledgeBase, kb_id)
    allowed = await visible_kb_ids(db, user)
    _ensure_visible(kb, user, allowed)
    ids = (
        await db.execute(select(KbDepartment.department_id).where(KbDepartment.kb_id == kb_id))
    ).scalars().all()
    return {"kb_id": kb_id, "department_ids": list(ids), "department_names": await _dept_names(db, kb_id)}


@router.put("/kb/{kb_id}/departments")
async def set_kb_departments(
    kb_id: int,
    body: KbDepartmentsIn,
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """整组覆盖授权部门"""
    kb = await db.get(KbKnowledgeBase, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if body.department_ids:
        found = (
            await db.execute(select(Department.id).where(Department.id.in_(body.department_ids)))
        ).scalars().all()
        if len(set(found)) != len(set(body.department_ids)):
            raise HTTPException(status_code=400, detail="存在不存在的部门")
    await db.execute(sa_delete(KbDepartment).where(KbDepartment.kb_id == kb_id))
    for dept_id in set(body.department_ids):
        db.add(KbDepartment(kb_id=kb_id, department_id=dept_id))
    await db.commit()
    return {"ok": True, "department_ids": sorted(set(body.department_ids))}


# ============ 文档管理 ============
@router.get("/kb/{kb_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    kb_id: int,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentOut]:
    kb = await db.get(KbKnowledgeBase, kb_id)
    allowed = await visible_kb_ids(db, user)
    _ensure_visible(kb, user, allowed)
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
    """上传文档（owner/admin）：md5 去重 → MinIO 存原文件 → 建记录 → 投递入库任务"""
    kb = await db.get(KbKnowledgeBase, kb_id)
    _ensure_can_write(kb, user)

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
    db: AsyncSession = Depends(get_db),
) -> dict:
    doc = await db.get(KbDocument, doc_id)
    if doc is not None:
        kb = await db.get(KbKnowledgeBase, doc.kb_id)
        _ensure_can_write(kb, user)
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
    kb = await db.get(KbKnowledgeBase, doc.kb_id)
    _ensure_can_write(kb, user)
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
    allowed = await visible_kb_ids(db, user)
    _ensure_visible(kb, user, allowed)
    stmt = select(KbChunk).where(KbChunk.kb_id == kb_id, KbChunk.is_parent == 0)
    if doc_id:
        stmt = stmt.where(KbChunk.doc_id == doc_id)
    stmt = stmt.order_by(KbChunk.doc_id, KbChunk.chunk_index).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return [ChunkOut.model_validate(r) for r in rows]
