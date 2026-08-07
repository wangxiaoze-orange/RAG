"""认证 API：注册（选部门申请加入） / 登录 / 当前用户
- 注册立即可用；所选部门生成待审批申请，管理员通过后写入 user.department_id
- 系统无管理员时，首个注册用户自动成为管理员
"""
import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_current_user, get_db
from src.core.security import create_access_token, hash_password, verify_password
from src.db.models import Department, DeptApply, User
from src.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/api/v2/auth", tags=["auth"])


async def _user_out(db: AsyncSession, row: User) -> UserOut:
    """UserOut 附带部门名称"""
    out = UserOut.model_validate(row)
    if row.department_id:
        dept = await db.get(Department, row.department_id)
        out.department_name = dept.name if dept else None
    return out


@router.post("/register", response_model=TokenOut)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    exists = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalars().first()
    if exists:
        raise HTTPException(status_code=409, detail="用户名已存在")

    # 部门校验（选了不存在的部门直接拒绝，避免脏申请）
    dept: Department | None = None
    if body.department_id:
        dept = await db.get(Department, body.department_id)
        if dept is None:
            raise HTTPException(status_code=400, detail="所选部门不存在")

    # 首个注册用户自动成为管理员（种子 admin 未创建时的兜底）
    total = (await db.execute(select(func.count(User.id)))).scalar() or 0
    has_admin = (
        await db.execute(select(func.count(User.id)).where(User.role == "admin"))
    ).scalar() or 0
    role = "admin" if (total == 0 or has_admin == 0) else "user"

    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        nickname=body.nickname or body.username,
        role=role,
        status=1,  # 注册即可用，部门待审批
    )
    db.add(user)
    await db.flush()

    if dept is not None:
        db.add(DeptApply(user_id=user.id, department_id=dept.id, status="pending"))
    await db.commit()
    await db.refresh(user)

    out = await _user_out(db, user)
    return TokenOut(token=create_access_token(user.id, user.username), user=out)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    user = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalars().first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.status != 1:
        raise HTTPException(status_code=403, detail="账号已禁用")
    user.last_login_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()
    out = await _user_out(db, user)
    return TokenOut(token=create_access_token(user.id, user.username), user=out)


@router.get("/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> UserOut:
    row = await db.get(User, user["user_id"])
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return await _user_out(db, row)
