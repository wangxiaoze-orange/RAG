"""用户与部门管理 API（管理员）：
- 部门 CRUD（管理员自定义）+ 注册页公开部门列表
- 用户列表 / 启用禁用 / 改角色 / 直接指派部门
- 入部申请审批（通过后写入 user.department_id）
"""
import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_current_user, get_db, require_admin
from src.db.models import Department, DeptApply, KbDepartment, User

router = APIRouter(prefix="/api/v2", tags=["user-manage"])


# ============ Schemas ============
class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)


class DepartmentOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    member_count: int = 0
    pending_count: int = 0
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class UserAdminOut(BaseModel):
    id: int
    username: str
    nickname: str | None = None
    email: str | None = None
    role: str = "user"
    department_id: int | None = None
    department_name: str | None = None
    status: int = 1
    last_login_at: datetime.datetime | None = None
    created_at: datetime.datetime

    class Config:
        from_attributes = True


class UserStatusIn(BaseModel):
    status: int = Field(ge=0, le=1)


class UserRoleIn(BaseModel):
    role: str = Field(pattern="^(admin|user)$")


class UserDeptIn(BaseModel):
    department_id: int | None = None


class ApplyOut(BaseModel):
    id: int
    user_id: int
    username: str
    nickname: str | None = None
    department_id: int
    department_name: str | None = None
    status: str
    created_at: datetime.datetime

    class Config:
        from_attributes = True


# ============ 公开：部门列表（注册页选部门） ============
@router.get("/departments/public")
async def public_departments(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(select(Department).order_by(Department.id))).scalars().all()
    return [{"id": r.id, "name": r.name, "description": r.description} for r in rows]


# ============ 部门管理（admin） ============
@router.get("/admin/departments")
async def list_departments(
    admin: dict = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[DepartmentOut]:
    depts = (await db.execute(select(Department).order_by(Department.id))).scalars().all()
    member_counts = dict(
        (await db.execute(
            select(User.department_id, func.count(User.id))
            .where(User.department_id.isnot(None))
            .group_by(User.department_id)
        )).all()
    )
    pending_counts = dict(
        (await db.execute(
            select(DeptApply.department_id, func.count(DeptApply.id))
            .where(DeptApply.status == "pending")
            .group_by(DeptApply.department_id)
        )).all()
    )
    outs = []
    for d in depts:
        out = DepartmentOut.model_validate(d)
        out.member_count = member_counts.get(d.id, 0)
        out.pending_count = pending_counts.get(d.id, 0)
        outs.append(out)
    return outs


@router.post("/admin/departments")
async def create_department(
    body: DepartmentIn, admin: dict = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    dup = (await db.execute(select(Department).where(Department.name == body.name))).scalars().first()
    if dup:
        raise HTTPException(status_code=409, detail="部门名称已存在")
    dept = Department(name=body.name, description=body.description, created_by=admin["user_id"])
    db.add(dept)
    await db.commit()
    await db.refresh(dept)
    return {"id": dept.id, "name": dept.name}


@router.put("/admin/departments/{dept_id}")
async def update_department(
    dept_id: int, body: DepartmentIn, admin: dict = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    dept = await db.get(Department, dept_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="部门不存在")
    dup = (
        await db.execute(select(Department).where(Department.name == body.name, Department.id != dept_id))
    ).scalars().first()
    if dup:
        raise HTTPException(status_code=409, detail="部门名称已存在")
    dept.name = body.name
    dept.description = body.description
    await db.commit()
    return {"ok": True}


@router.delete("/admin/departments/{dept_id}")
async def delete_department(
    dept_id: int, admin: dict = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    dept = await db.get(Department, dept_id)
    if dept is None:
        raise HTTPException(status_code=404, detail="部门不存在")
    members = (
        await db.execute(select(func.count(User.id)).where(User.department_id == dept_id))
    ).scalar() or 0
    if members:
        raise HTTPException(status_code=400, detail=f"部门下仍有 {members} 名成员，请先转移或清空成员")
    await db.execute(sa_delete(KbDepartment).where(KbDepartment.department_id == dept_id))
    await db.execute(sa_delete(DeptApply).where(DeptApply.department_id == dept_id))
    await db.delete(dept)
    await db.commit()
    return {"ok": True}


# ============ 用户管理（admin） ============
@router.get("/admin/users")
async def list_users(
    keyword: str = Query(default=""),
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[UserAdminOut]:
    stmt = select(User).order_by(User.id)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where((User.username.like(like)) | (User.nickname.like(like)))
    rows = (await db.execute(stmt)).scalars().all()
    dept_ids = {r.department_id for r in rows if r.department_id}
    dept_map: dict[int, str] = {}
    if dept_ids:
        depts = (await db.execute(select(Department).where(Department.id.in_(dept_ids)))).scalars().all()
        dept_map = {d.id: d.name for d in depts}
    outs = []
    for r in rows:
        out = UserAdminOut.model_validate(r)
        out.department_name = dept_map.get(r.department_id) if r.department_id else None
        outs.append(out)
    return outs


@router.put("/admin/users/{user_id}/status")
async def set_user_status(
    user_id: int, body: UserStatusIn, admin: dict = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    if user_id == admin["user_id"] and body.status == 0:
        raise HTTPException(status_code=400, detail="不能禁用自己的账号")
    row = await db.get(User, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    row.status = body.status
    await db.commit()
    return {"ok": True}


@router.put("/admin/users/{user_id}/role")
async def set_user_role(
    user_id: int, body: UserRoleIn, admin: dict = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    if user_id == admin["user_id"] and body.role != "admin":
        raise HTTPException(status_code=400, detail="不能取消自己的管理员权限")
    row = await db.get(User, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    row.role = body.role
    await db.commit()
    return {"ok": True}


@router.put("/admin/users/{user_id}/department")
async def set_user_department(
    user_id: int, body: UserDeptIn, admin: dict = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    """管理员直接指派部门（同时把该用户针对此部门的待审申请置为通过）"""
    row = await db.get(User, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if body.department_id is not None:
        dept = await db.get(Department, body.department_id)
        if dept is None:
            raise HTTPException(status_code=404, detail="部门不存在")
    row.department_id = body.department_id
    if body.department_id is not None:
        applies = (
            await db.execute(
                select(DeptApply).where(
                    DeptApply.user_id == user_id,
                    DeptApply.department_id == body.department_id,
                    DeptApply.status == "pending",
                )
            )
        ).scalars().all()
        now = datetime.datetime.now(datetime.timezone.utc)
        for a in applies:
            a.status = "approved"
            a.reviewed_by = admin["user_id"]
            a.reviewed_at = now
    await db.commit()
    return {"ok": True}


# ============ 入部申请审批（admin） ============
@router.get("/admin/applications")
async def list_applications(
    status: str = Query(default="pending"),
    admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> list[ApplyOut]:
    stmt = select(DeptApply).order_by(DeptApply.id.desc()).limit(200)
    if status != "all":
        stmt = stmt.where(DeptApply.status == status)
    applies = (await db.execute(stmt)).scalars().all()
    user_ids = {a.user_id for a in applies}
    dept_ids = {a.department_id for a in applies}
    user_map: dict[int, User] = {}
    dept_map: dict[int, str] = {}
    if user_ids:
        users = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        user_map = {u.id: u for u in users}
    if dept_ids:
        depts = (await db.execute(select(Department).where(Department.id.in_(dept_ids)))).scalars().all()
        dept_map = {d.id: d.name for d in depts}
    outs = []
    for a in applies:
        u = user_map.get(a.user_id)
        outs.append(ApplyOut(
            id=a.id,
            user_id=a.user_id,
            username=u.username if u else f"#{a.user_id}",
            nickname=u.nickname if u else None,
            department_id=a.department_id,
            department_name=dept_map.get(a.department_id),
            status=a.status,
            created_at=a.created_at,
        ))
    return outs


async def _review_apply(apply_id: int, approve: bool, admin: dict, db: AsyncSession) -> dict:
    apply = await db.get(DeptApply, apply_id)
    if apply is None:
        raise HTTPException(status_code=404, detail="申请不存在")
    if apply.status != "pending":
        raise HTTPException(status_code=400, detail="该申请已处理")
    now = datetime.datetime.now(datetime.timezone.utc)
    apply.status = "approved" if approve else "rejected"
    apply.reviewed_by = admin["user_id"]
    apply.reviewed_at = now
    if approve:
        user = await db.get(User, apply.user_id)
        if user:
            user.department_id = apply.department_id
    await db.commit()
    return {"ok": True, "status": apply.status}


@router.post("/admin/applications/{apply_id}/approve")
async def approve_application(
    apply_id: int, admin: dict = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    return await _review_apply(apply_id, True, admin, db)


@router.post("/admin/applications/{apply_id}/reject")
async def reject_application(
    apply_id: int, admin: dict = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    return await _review_apply(apply_id, False, admin, db)


# ============ 当前用户可见部门状态（普通用户） ============
@router.get("/my-department")
async def my_department(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> dict:
    """返回当前用户的部门归属与申请状态（前端提示用）"""
    if user["department_id"]:
        dept = await db.get(Department, user["department_id"])
        return {"status": "approved", "department_id": dept.id if dept else None, "department_name": dept.name if dept else None}
    pending = (
        await db.execute(
            select(DeptApply).where(DeptApply.user_id == user["user_id"], DeptApply.status == "pending")
            .order_by(DeptApply.id.desc())
        )
    ).scalars().first()
    if pending:
        dept = await db.get(Department, pending.department_id)
        return {"status": "pending", "department_id": dept.id if dept else None, "department_name": dept.name if dept else None}
    return {"status": "none", "department_id": None, "department_name": None}
