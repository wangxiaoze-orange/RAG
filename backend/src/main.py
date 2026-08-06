"""FastAPI 入口：CORS / 路由 / 启动预热"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.router import api_router
from src.config.settings import settings
from src.core.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动预热：MinIO 桶确保存在（中间件未就绪时失败仅告警，不影响启动）
    try:
        from src.core.minio_client import get_minio
        await get_minio().ensure_bucket()
    except Exception as e:  # noqa: BLE001
        logger.warning("MinIO 预热失败（确认中间件已启动）: %s", e)
    yield


app = FastAPI(title="RAG 智能问答系统", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health() -> dict:
    """存活探针"""
    return {"status": "ok", "service": "rag-backend"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=settings.backend_host, port=settings.backend_port, reload=True)
