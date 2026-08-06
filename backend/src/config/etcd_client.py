"""etcd 客户端封装：etcd v3 gRPC-gateway HTTP API（httpx，纯异步，零 protobuf 依赖）

为什么不用 etcd3 库：etcd3 0.12.0 的 proto 桩要求 protobuf<3.21，
而 pymilvus 2.5.4 的桩由 protoc 4.25.1 生成、需要 >=4.22，两者无法共存。
etcd v3 默认在客户端端口（2379）暴露 HTTP API（/v3/kv/range|put|deleterange），
key/value 按协议 base64 编码，httpx 直连即可，单键读写场景性能等同 gRPC。
"""
import base64
import logging
from functools import lru_cache

import httpx

from src.config.settings import settings

logger = logging.getLogger(__name__)


def _b64(data: str) -> str:
    return base64.b64encode(data.encode("utf-8")).decode("ascii")


class EtcdClient:
    """etcd v3 HTTP 客户端（进程内复用单个 httpx AsyncClient）"""

    def __init__(self, endpoints: str | None = None):
        # 支持 "host:port" 或 "host1:port1,host2:port2"（多节点取第一个）或完整 URL
        ep = (endpoints or settings.etcd_endpoints).split(",")[0].strip()
        if "://" not in ep:
            ep = f"http://{ep}"
        self._base = ep.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self._base, timeout=10.0)
        logger.info("etcd 客户端初始化: %s", self._base)

    async def _kv(self, op: str, payload: dict) -> dict:
        resp = await self._http.post(f"/v3/kv/{op}", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get(self, key: str) -> str | None:
        """单键读取；不存在返回 None"""
        data = await self._kv("range", {"key": _b64(key)})
        kvs = data.get("kvs") or []
        return base64.b64decode(kvs[0]["value"]).decode("utf-8") if kvs else None

    async def put(self, key: str, value: str) -> None:
        await self._kv("put", {"key": _b64(key), "value": _b64(value)})

    async def delete(self, key: str) -> None:
        await self._kv("deleterange", {"key": _b64(key)})

    async def get_prefix(self, prefix: str) -> dict[str, str]:
        """返回 {完整key: 值}（range_end = prefix + \0 实现前缀扫描）"""
        data = await self._kv("range", {
            "key": _b64(prefix),
            "range_end": _b64(prefix + "\0"),
            "limit": 0,  # 0 = 不限条数
        })
        result = {}
        for kv in data.get("kvs") or []:
            key = base64.b64decode(kv["key"]).decode("utf-8")
            value = base64.b64decode(kv["value"]).decode("utf-8")
            result[key] = value
        return result

    async def health(self) -> bool:
        try:
            resp = await self._http.get("/health", timeout=3.0)
            return resp.status_code == 200 and resp.json().get("health") == "true"
        except Exception:  # noqa: BLE001
            return False


@lru_cache(maxsize=1)
def get_etcd_client() -> EtcdClient:
    return EtcdClient()
