"""数据库初始化（幂等，可重复执行）：
1. Base.metadata.create_all 建表（11 张，deploy/mysql/init/01_schema.sql 的代码态镜像）
2. seed admin 账号（.env 的 SEED_ADMIN_USERNAME / SEED_ADMIN_PASSWORD）
3. 内置 5 个供应商（siliconflow/qwen/deepseek/vllm/ollama）写入 MySQL 兜底表
用法：python -m src.scripts.init_db
"""
import asyncio
import logging

from sqlalchemy import select

from src.config.settings import settings
from src.core.security import hash_password
from src.db.migrate import ensure_columns
from src.db.models import Base, ModelProvider, RagConfig, User
from src.db.session import async_session_maker, engine
from src.providers.encrypt import encrypt_secret
from src.providers.manager import BUILTIN_PROVIDERS

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        added = await ensure_columns(conn)
    logger.info("数据表已就绪（补列 %d 个）", added)


async def seed_admin() -> None:
    async with async_session_maker() as session:
        existing = (
            await session.execute(select(User).where(User.username == settings.seed_admin_username))
        ).scalars().first()
        if existing:
            if existing.role != "admin":
                existing.role = "admin"
                await session.commit()
                logger.info("种子账号 %s 已升级为 admin", existing.username)
            else:
                logger.info("admin 已存在，跳过")
            return
        session.add(User(
            username=settings.seed_admin_username,
            password_hash=hash_password(settings.seed_admin_password),
            nickname="管理员",
            role="admin",
        ))
        await session.commit()
        logger.info("admin 已创建: %s", settings.seed_admin_username)


async def seed_providers() -> None:
    async with async_session_maker() as session:
        existing = (await session.execute(select(ModelProvider))).scalars().all()
        have = {r.name for r in existing}
        for name, cfg in BUILTIN_PROVIDERS.items():
            if name in have:
                continue
            row = ModelProvider(
                name=cfg.name,
                provider_type=cfg.provider_type,
                base_url=cfg.base_url,
                api_key=encrypt_secret(cfg.api_key or ""),
                model=cfg.model,
                embedding_model=cfg.embedding_model,
                rerank_model=cfg.rerank_model,
                extra=cfg.extra,
                is_default=1 if cfg.is_default else 0,
                enabled=1 if cfg.enabled else 0,
            )
            session.add(row)
        await session.commit()
        logger.info("内置供应商种子完成（已存在 %d 个，本次新增 %d 个）", len(have), len(BUILTIN_PROVIDERS) - len(have))


async def seed_default_config() -> None:
    """把本地默认参数写入 MySQL rag_config（etcd 在线时会被 etcd 覆盖，仅兜底）"""
    defaults = {
        "rag.cache_freq_threshold": 3,
        "rag.cache_write_min_freq": 3,
        "rag.cache_ttl_seconds": 604800,
        "rag.document_scope_chunk_budget": 18,
        "rag.rrf_top_k": 15,
        "rag.rerank_top_n": 6,
        "rag.compress_budget_tokens": 3000,
        "rag.confidence_threshold": 0.20,
        "rag.reflection_threshold": 0.4,
        "rag.memory_ttl_days": 30,
        "rag.web_search_timeout_seconds": 8,
        "rag.temperature": 0.7,
        "rag.recall_total": 20,
        "rag.intent.label_weights": {
            "need_vector": 1.0,
            "need_bm25": 1.0,
            "need_web": 0.8,
            "need_memory": 0.5,
            "need_fact_check": 0.9,
            "need_summary": 0.8,
            "need_comparison": 0.9,
        },
        "rag.feature.cache_enabled": True,
        "rag.feature.faq_enabled": True,
        "rag.feature.web_search_enabled": True,
        "rag.feature.agent_retrieval_enabled": True,
    }
    async with async_session_maker() as session:
        for key, value in defaults.items():
            row = await session.get(RagConfig, key)
            if row is None:
                session.add(RagConfig(config_key=key, value=value))
        await session.commit()
        logger.info("默认配置种子完成（%d 项）", len(defaults))


async def main() -> None:
    await create_tables()
    await seed_admin()
    await seed_providers()
    await seed_default_config()
    await engine.dispose()
    logger.info("初始化完成 ✅")


if __name__ == "__main__":
    asyncio.run(main())
