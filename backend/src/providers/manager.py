"""供应商管理：etcd 主存储（/config/providers/{name}），MySQL model_provider 兜底
- 读取：etcd 前缀 → 空则 MySQL → 内置默认
- 写入：etcd + MySQL 双写（api_key 在 MySQL 侧 Fernet 加密）
"""
import asyncio
import logging
import time

import httpx
from sqlalchemy import select

from src.config.etcd_client import get_etcd_client
from src.config.settings import settings
from src.db.models import ModelProvider
from src.db.session import async_session_maker
from src.providers.base import ProviderConfig
from src.providers.encrypt import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

PROVIDER_PREFIX = "/config/providers/"

# 已知嵌入/重排模型补充表：多数厂商的 OpenAI 兼容 /models 接口只返回对话模型
# （典型如 DashScope 只列 qwen-*），测试探测后把这些已知型号并入结果，
# 前端按名称启发式分类进 嵌入/重排 下拉框。随厂商上新可自行增补。
SUPPLEMENT_MODELS: dict[str, list[str]] = {
    "qwen": [
        "text-embedding-v4", "text-embedding-v3", "text-embedding-v2", "text-embedding-v1",
        "gte-rerank-v2", "gte-rerank",
    ],
    "siliconflow": [
        "BAAI/bge-m3", "BAAI/bge-large-zh-v1.5", "BAAI/bge-large-en-v1.5",
        "netease-youdao/bce-embedding-base_v1", "Qwen/Qwen3-Embedding-0.6B",
        "BAAI/bge-reranker-v2-m3", "BAAI/bge-reranker-large", "BAAI/bge-reranker-base",
        "Qwen/Qwen3-Reranker-0.6B",
    ],
    "ollama": [
        "nomic-embed-text", "mxbai-embed-large", "all-minilm",
    ],
}

# 内置默认供应商（etcd 与 MySQL 都无数据时的兜底）
BUILTIN_PROVIDERS: dict[str, ProviderConfig] = {
    "siliconflow": ProviderConfig(
        name="siliconflow",
        provider_type="siliconflow",
        base_url="https://api.siliconflow.cn/v1",
        model="Qwen/Qwen2.5-7B-Instruct",
        embedding_model="BAAI/bge-m3",
        rerank_model="BAAI/bge-reranker-v2-m3",
        is_default=True,
    ),
    "qwen": ProviderConfig(
        name="qwen",
        provider_type="qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        embedding_model="text-embedding-v3",
    ),
    "deepseek": ProviderConfig(
        name="deepseek",
        provider_type="deepseek",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    ),
    "vllm": ProviderConfig(
        name="vllm",
        provider_type="vllm",
        base_url="http://127.0.0.1:8000/v1",
        api_key="EMPTY",
        model="Qwen2.5-7B-Instruct",
    ),
    "ollama": ProviderConfig(
        name="ollama",
        provider_type="ollama",
        base_url="http://127.0.0.1:11434/v1",
        api_key="ollama",
        model="qwen2.5:7b",
    ),
}


class ProviderManager:
    def __init__(self) -> None:
        self._cache: dict[str, ProviderConfig] = {}
        self._cache_ts = 0.0
        self._cache_ttl = 30.0  # 秒
        self._lock = asyncio.Lock()

    # ---------- 读取 ----------
    async def list_providers(self, force: bool = False) -> list[ProviderConfig]:
        now = time.monotonic()
        if not force and self._cache and now - self._cache_ts < self._cache_ttl:
            return list(self._cache.values())

        async with self._lock:
            now = time.monotonic()
            if self._cache and now - self._cache_ts < self._cache_ttl:
                return list(self._cache.values())

            merged: dict[str, ProviderConfig] = {}
            try:
                raw = await get_etcd_client().get_prefix(PROVIDER_PREFIX)
                for key, value in raw.items():
                    name = key[len(PROVIDER_PREFIX):]
                    merged[name] = ProviderConfig.from_json(name, value)
                if raw:
                    logger.info("从 etcd 加载供应商 %d 个", len(raw))
            except Exception as e:  # noqa: BLE001
                logger.warning("etcd 供应商读取失败: %s", e)

            if not merged:
                # etcd 无数据 → MySQL 兜底
                try:
                    async with async_session_maker() as session:
                        rows = (await session.execute(select(ModelProvider))).scalars().all()
                    for r in rows:
                        cfg = ProviderConfig(
                            name=r.name,
                            provider_type=r.provider_type,
                            base_url=r.base_url,
                            api_key=decrypt_secret(r.api_key or ""),
                            model=r.model,
                            embedding_model=r.embedding_model,
                            rerank_model=r.rerank_model,
                            extra=r.extra or {},
                            is_default=bool(r.is_default),
                            enabled=bool(r.enabled),
                            id=r.id,
                        )
                        merged[cfg.name] = cfg
                    if merged:
                        logger.info("从 MySQL 兜底加载供应商 %d 个", len(merged))
                except Exception as e:  # noqa: BLE001
                    logger.warning("MySQL 供应商兜底失败: %s", e)

            if not merged:
                merged = dict(BUILTIN_PROVIDERS)
                logger.warning("etcd/MySQL 均无供应商配置，使用内置默认")

            # 启用过滤
            self._cache = {k: v for k, v in merged.items() if v.enabled}
            self._cache_ts = time.monotonic()
            return list(self._cache.values())

    async def get(self, name: str) -> ProviderConfig | None:
        providers = await self.list_providers()
        return next((p for p in providers if p.name == name), None)

    async def get_default(self) -> ProviderConfig | None:
        providers = await self.list_providers()
        return next((p for p in providers if p.is_default), providers[0] if providers else None)

    # ---------- 写入（双写） ----------
    async def upsert(self, cfg: ProviderConfig) -> None:
        key = f"{PROVIDER_PREFIX}{cfg.name}"
        # etcd 存明文 api_key（etcd 本身是受信存储）
        await get_etcd_client().put(key, cfg.to_json(mask_key=False))
        # MySQL 兜底（api_key 加密）
        try:
            async with async_session_maker() as session:
                row = (
                    await session.execute(
                        select(ModelProvider).where(ModelProvider.name == cfg.name)
                    )
                ).scalars().first()
                if row is None:
                    row = ModelProvider(name=cfg.name)
                    session.add(row)
                row.provider_type = cfg.provider_type
                row.base_url = cfg.base_url
                row.api_key = encrypt_secret(cfg.api_key)
                row.model = cfg.model
                row.embedding_model = cfg.embedding_model
                row.rerank_model = cfg.rerank_model
                row.extra = cfg.extra
                row.is_default = 1 if cfg.is_default else 0
                row.enabled = 1 if cfg.enabled else 0
                row.etcd_key = key
                await session.commit()
                cfg.id = row.id
        except Exception as e:  # noqa: BLE001
            logger.warning("MySQL 供应商写入失败: %s", e)
        # 刷新缓存
        await self.list_providers(force=True)

    async def set_default(self, name: str) -> None:
        """切换全局默认供应商"""
        providers = await self.list_providers(force=True)
        for p in providers:
            p.is_default = (p.name == name)
        for p in providers:
            await get_etcd_client().put(
                f"{PROVIDER_PREFIX}{p.name}", p.to_json(mask_key=False)
            )
        try:
            async with async_session_maker() as session:
                rows = (await session.execute(select(ModelProvider))).scalars().all()
                for r in rows:
                    r.is_default = 1 if r.name == name else 0
                await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("MySQL 默认供应商更新失败: %s", e)
        await self.list_providers(force=True)

    async def delete(self, name: str) -> None:
        try:
            await get_etcd_client().delete(f"{PROVIDER_PREFIX}{name}")
        except Exception as e:  # noqa: BLE001
            logger.warning("etcd 供应商删除失败: %s", e)
        try:
            async with async_session_maker() as session:
                row = (
                    await session.execute(
                        select(ModelProvider).where(ModelProvider.name == name)
                    )
                ).scalars().first()
                if row:
                    await session.delete(row)
                    await session.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("MySQL 供应商删除失败: %s", e)
        self._cache.pop(name, None)

    # ---------- 连通性测试 ----------
    async def test_connection(self, cfg: ProviderConfig, model: str | None = None) -> dict:
        """GET {base_url}/models 校验连通；model 非空时再用该模型做 1-token 对话试跑，
        返回可用模型列表；试跑失败抛 RuntimeError（含具体 HTTP 错误）"""
        headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{cfg.base_url.rstrip('/')}/models", headers=headers)
            resp.raise_for_status()
            models = [m.get("id") for m in resp.json().get("data", [])][:20]

            # ── 补充探测：/models 之外的模型（嵌入/重排通常不列在这） ──
            # 1) Ollama：OpenAI 兼容 /models 只列对话模型，原生 /api/tags 能列出全部（含嵌入）
            if cfg.provider_type == "ollama":
                try:
                    base = cfg.base_url.rstrip("/").removesuffix("/v1")
                    tags = await client.get(f"{base}/api/tags")
                    if tags.status_code == 200:
                        for m in tags.json().get("models", []):
                            name = str(m.get("name") or "").rsplit(":", 1)[0]  # 去掉 :latest 版本号
                            if name and name not in models:
                                models.append(name)
                except Exception as e:  # noqa: BLE001
                    logger.debug("Ollama /api/tags 探测失败: %s", e)
            # 2) 供应商已知嵌入/重排模型（去重后并入，前端按名称分类）
            for m in SUPPLEMENT_MODELS.get(cfg.provider_type, []):
                if m not in models:
                    models.append(m)
            models = models[:50]

            if model:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                }
                try:
                    r = await client.post(
                        f"{cfg.base_url.rstrip('/')}/chat/completions",
                        json=payload,
                        headers=headers,
                    )
                    r.raise_for_status()
                except httpx.HTTPStatusError as e:
                    raise RuntimeError(
                        f"模型 {model} 试跑失败: HTTP {e.response.status_code}: {e.response.text[:200]}"
                    ) from e
        return {"ok": True, "model_count": len(models), "models": models, "model_tested": model}


provider_manager = ProviderManager()
