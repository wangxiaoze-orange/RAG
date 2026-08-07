"""FastAPI 依赖注入：DB 会话 / 当前用户 / 配置中心 / 供应商管理 / Redis"""
from typing import AsyncIterator

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config.config_center import ConfigCenter, config_center
from src.core.security import decode_token
from src.db.models import User
from src.db.redis import get_redis
from src.db.session import async_session_maker
from src.providers.manager import ProviderManager, provider_manager

_bearer = HTTPBearer(auto_error=False)


async def get_db():
    """请求级异步数据库会话"""
    async with async_session_maker() as session:
        yield session


async def get_redis_client() -> aioredis.Redis:
    return get_redis()


async def get_config_center() -> ConfigCenter:
    return config_center


async def get_provider_manager() -> ProviderManager:
    return provider_manager


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """从 JWT 解析当前用户，并查库补齐角色/部门；未登录/失效/禁用返回 401"""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌")
    async with async_session_maker() as session:
        row = await session.get(User, user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不存在")
    if row.status != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已禁用")
    return {
        "user_id": user_id,
        "username": row.username,
        "role": row.role or "user",
        "department_id": row.department_id,
    }


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """管理员专用依赖：非 admin 一律 403"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user
