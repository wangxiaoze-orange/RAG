"""MinIO 客户端单例：非结构化原文件 / 解析中间产物存储"""
import asyncio
import io
import logging
from functools import lru_cache

from minio import Minio

from src.config.settings import settings

logger = logging.getLogger(__name__)


class MinioService:
    def __init__(self) -> None:
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        self.bucket = settings.minio_bucket

    async def ensure_bucket(self) -> None:
        """启动时确保桶存在"""
        def _ensure() -> None:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info("MinIO 桶已创建: %s", self.bucket)
        await asyncio.to_thread(_ensure)

    async def put_bytes(self, object_name: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        def _put() -> str:
            self.client.put_object(
                self.bucket,
                object_name,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            return object_name
        return await asyncio.to_thread(_put)

    async def get_bytes(self, object_name: str) -> bytes:
        def _get() -> bytes:
            resp = self.client.get_object(self.bucket, object_name)
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()
        return await asyncio.to_thread(_get)

    async def exists(self, object_name: str) -> bool:
        def _exists() -> bool:
            try:
                self.client.stat_object(self.bucket, object_name)
                return True
            except Exception:  # noqa: BLE001
                return False
        return await asyncio.to_thread(_exists)

    async def remove(self, object_name: str) -> None:
        def _remove() -> None:
            try:
                self.client.remove_object(self.bucket, object_name)
            except Exception as e:  # noqa: BLE001
                logger.debug("MinIO 删除失败 %s: %s", object_name, e)
        await asyncio.to_thread(_remove)


@lru_cache(maxsize=1)
def get_minio() -> MinioService:
    return MinioService()
