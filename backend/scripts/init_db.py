"""数据库初始化：建表（幂等）+ 种子数据（admin 用户 + 默认供应商入 MySQL 兜底）
用法（在 backend/ 目录下）：
    python scripts/init_db.py
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from src.config.settings import settings  # noqa: E402
from src.core.logging import setup_logging  # noqa: E402
from src.core.security import hash_password  # noqa: E402
from src.db import Base, engine, async_session_maker  # noqa: E402
from src.db import models  # noqa: F401,E402  确保模型注册
from src.providers.base import ProviderConfig  # noqa: E402
from src.providers.encrypt import encrypt_secret  # noqa: E402
from src.providers.manager import BUILTIN_PROVIDERS  # noqa: E402

setup_logging()
logger = logging.getLogger("init_db")


async def init() -> None:
    # 1. 建表（CREATE TABLE IF NOT EXISTS 幂等）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("数据表就绪")

    async with async_session_maker() as session:
        # 2. 种子 admin 用户
        from src.db.models import ModelProvider, User
        admin = (
            await session.execute(
                select(User).where(User.username == settings.seed_admin_username)
            )
        ).scalars().first()
        if admin is None:
            session.add(
                User(
                    username=settings.seed_admin_username,
                    password_hash=hash_password(settings.seed_admin_password),
                    nickname="管理员",
                )
            )
            logger.info("种子 admin 用户已创建（%s / %s）", settings.seed_admin_username, settings.seed_admin_password)

        # 3. 种子默认供应商（MySQL 兜底，etcd 不可用时仍可用）
        existing = {
            r.name
            for r in (await session.execute(select(ModelProvider))).scalars().all()
        }
        for name, cfg in BUILTIN_PROVIDERS.items():
            if name in existing:
                continue
            session.add(
                ModelProvider(
                    name=name,
                    provider_type=cfg.provider_type,
                    base_url=cfg.base_url,
                    api_key=encrypt_secret(cfg.api_key),
                    model=cfg.model,
                    embedding_model=cfg.embedding_model,
                    rerank_model=cfg.rerank_model,
                    is_default=1 if cfg.is_default else 0,
                    enabled=1,
                    etcd_key=f"/config/providers/{name}",
                )
            )
        await session.commit()
        logger.info("种子供应商 %d 个已就绪", len(BUILTIN_PROVIDERS))


if __name__ == "__main__":
    asyncio.run(init())
    logger.info("数据库初始化完成")
