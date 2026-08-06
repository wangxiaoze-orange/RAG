"""api_key 加密存储：Fernet 对称加密，密钥由 SECRET_KEY 派生"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from src.config.settings import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
        _fernet = Fernet(key)
    return _fernet


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    return _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        # 兼容未加密的历史数据（etcd 种子中 api_key 为空串不会走到这里）
        return token
