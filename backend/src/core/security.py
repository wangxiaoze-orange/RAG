"""安全模块：bcrypt 密码哈希 + JWT 签发/校验"""
import datetime
import logging
from typing import Any

import bcrypt
import jwt

from src.config.settings import settings

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """bcrypt 哈希（自带随机盐）"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, username: str, expire_minutes: int | None = None) -> str:
    """签发 JWT，过期时间默认 settings.jwt_expire_minutes"""
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "iat": datetime.datetime.now(datetime.timezone.utc),
        "exp": datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(minutes=expire_minutes or settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any] | None:
    """校验并解析 JWT；无效/过期返回 None"""
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as e:
        logger.debug("JWT 校验失败: %s", e)
        return None
