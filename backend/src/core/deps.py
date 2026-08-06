"""FastAPI 依赖注入：DB 会话 / 当前用户 / 配置中心 / 供应商管理 / Redis"""
from typing import AsyncIterator

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.config.config_center import ConfigCenter, config_center
from src.core.security import decode_token
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
    """从 JWT 解析当前用户 {user_id, username}；未登录/失效返回 401"""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已过期，请重新登录")
    try:
        return {"user_id": int(payload["sub"]), "username": payload.get("username", "")}
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效令牌")
