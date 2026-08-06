"""arq 入库 worker 入口
启动（在 backend/ 目录下）：
    python -m src.ingestion.worker
"""
import asyncio
import logging

from arq import Worker
from arq.connections import RedisSettings

from src.config.settings import settings
from src.core.logging import setup_logging
from src.ingestion.tasks import process_document

setup_logging()
logger = logging.getLogger(__name__)


async def startup(ctx) -> None:
    logger.info("入库 worker 启动")


async def shutdown(ctx) -> None:
    logger.info("入库 worker 关闭")


class WorkerSettings:
    functions = [process_document]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_tries = 3                     # 单任务最多重试 3 次
    job_timeout = 1800                # 单任务最长 30 分钟
    on_startup = startup
    on_shutdown = shutdown


def main() -> None:
    asyncio.run(Worker(WorkerSettings).run())


if __name__ == "__main__":
    main()
