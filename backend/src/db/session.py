"""SQLAlchemy 2.0 异步引擎与会话工厂"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.config.settings import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,     # 取连接前探测，避免断线
    pool_recycle=3600,      # 连接 1 小时回收
    echo=False,
)

async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    """FastAPI 依赖：请求级会话，自动关闭"""
    async with async_session_maker() as session:
        yield session
