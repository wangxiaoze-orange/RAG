"""认证 API：注册 / 登录 / 当前用户"""
import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.deps import get_current_user, get_db
from src.core.security import create_access_token, hash_password, verify_password
from src.db.models import User
from src.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/api/v2/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut)
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)) -> TokenOut:
    exists = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalars().first()
    if exists:
        raise HTTPException(status_code=409, detail="用户名已存在")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        nickname=body.nickname or body.username,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return TokenOut(token=create_access_token(user.id, user.username), user=UserOut.model_validate(user))


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
    return TokenOut(token=create_access_token(user.id, user.username), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> UserOut:
    row = await db.get(User, user["user_id"])
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return UserOut.model_validate(row)
