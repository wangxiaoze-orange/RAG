"""配置中心：三级降级读取（etcd → MySQL rag_config 兜底表 → 本地默认值）+ 本地 TTL 缓存
写入走双写（etcd 成功 + MySQL 同步），任一失败仍可用
"""
import asyncio
import json
import logging
import time
from typing import Any

from src.config.etcd_client import get_etcd_client
from src.config.settings import settings
from src.db.models import RagConfig
from src.db.session import async_session_maker

logger = logging.getLogger(__name__)


class ConfigCenter:
    """rag.* 可调参数与特征开关的统一读取入口"""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, str | None]] = {}  # key -> (ts, value)
        self._cache_ttl = 10.0  # 秒
        self._lock = asyncio.Lock()

    @staticmethod
    def _etcd_key(key: str) -> str:
        """点号键 → etcd 层级路径：rag.xxx.yyy → /config/rag/xxx/yyy；其余 → /config/{key}
        （MySQL rag_config 表仍存点号原始键；etcd 侧用层级目录便于 etcdctl 浏览）"""
        if key.startswith("rag."):
            return f"{settings.etcd_prefix}/rag/{key[4:].replace('.', '/')}"
        return f"{settings.etcd_prefix}/{key}"

    # ---------- 底层读取 ----------
    async def _from_etcd(self, key: str) -> str | None:
        try:
            return await get_etcd_client().get(self._etcd_key(key))
        except Exception as e:  # noqa: BLE001
            logger.warning("etcd 读取失败 %s: %s", key, e)
            return None

    async def _from_db(self, key: str) -> str | None:
        try:
            async with async_session_maker() as session:
                row = await session.get(RagConfig, key)
                if row and row.value is not None:
                    return json.dumps(row.value, ensure_ascii=False)
        except Exception as e:  # noqa: BLE001
            logger.warning("MySQL 兜底读取失败 %s: %s", key, e)
        return None

    # ---------- 对外读取 ----------
    async def get_raw(self, key: str, default: str | None = None) -> str | None:
        """三级读取：etcd → MySQL → default，带 TTL 缓存"""
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and now - cached[0] < self._cache_ttl:
            return cached[1] if cached[1] is not None else default

        value = await self._from_etcd(key)
        if value is None:
            value = await self._from_db(key)
        async with self._lock:
            self._cache[key] = (time.monotonic(), value)
        return value if value is not None else default

    async def get(self, key: str, default: str = "") -> str:
        return (await self.get_raw(key, default)) or default

    async def get_int(self, key: str, default: int) -> int:
        raw = await self.get_raw(key)
        try:
            return int(raw) if raw is not None else default
        except (TypeError, ValueError):
            return default

    async def get_bool(self, key: str, default: bool) -> bool:
        raw = await self.get_raw(key)
        if raw is None:
            return default
        return str(raw).strip().lower() in ("1", "true", "yes", "on")

    async def get_float(self, key: str, default: float) -> float:
        raw = await self.get_raw(key)
        try:
            return float(raw) if raw is not None else default
        except (TypeError, ValueError):
            return default

    async def get_json(self, key: str, default: Any = None) -> Any:
        raw = await self.get_raw(key)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    async def get_prefix(self, prefix: str) -> dict[str, str]:
        """读某前缀下全部键（etcd 优先，MySQL 前缀兜底）"""
        try:
            data = await get_etcd_client().get_prefix(prefix)
            if data:
                return data
        except Exception as e:  # noqa: BLE001
            logger.warning("etcd 前缀读取失败 %s: %s", prefix, e)
        try:
            async with async_session_maker() as session:
                from sqlalchemy import select
                rows = (await session.execute(select(RagConfig).where(RagConfig.config_key.like(f"{prefix}%")))).scalars().all()
                return {r.config_key: json.dumps(r.value, ensure_ascii=False) for r in rows}
        except Exception as e:  # noqa: BLE001
            logger.warning("MySQL 前缀兜底失败 %s: %s", prefix, e)
        return {}

    # ---------- 写入（双写） ----------
    async def set(self, key: str, value: str) -> None:
        """etcd + MySQL 双写；etcd 失败仅告警（MySQL 仍可用作兜底）"""
        try:
            await get_etcd_client().put(self._etcd_key(key), value)
        except Exception as e:  # noqa: BLE001
            logger.warning("etcd 写入失败 %s: %s", key, e)
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        try:
            async with async_session_maker() as session:
                row = await session.get(RagConfig, key)
                if row:
                    row.value = parsed
                else:
                    session.add(RagConfig(config_key=key, value=parsed))
                await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("MySQL 兜底写入失败 %s: %s", key, e)
        async with self._lock:
            self._cache[key] = (time.monotonic(), value)

    async def delete(self, key: str) -> None:
        try:
            await get_etcd_client().delete(self._etcd_key(key))
        except Exception as e:  # noqa: BLE001
            logger.warning("etcd 删除失败 %s: %s", key, e)
        try:
            async with async_session_maker() as session:
                row = await session.get(RagConfig, key)
                if row:
                    await session.delete(row)
                    await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("MySQL 兜底删除失败 %s: %s", key, e)
        self._cache.pop(key, None)


config_center = ConfigCenter()
