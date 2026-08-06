"""应用配置：从 .env / 环境变量读取，作为配置中心的本地默认值兜底（第三级）"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 服务监听 ----------
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8901

    # ---------- MySQL ----------
    database_url: str = "mysql+aiomysql://rag:rag_123456@127.0.0.1:3306/rag?charset=utf8mb4"

    # ---------- Redis ----------
    redis_url: str = "redis://127.0.0.1:6379/0"

    # ---------- MinIO ----------
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "rag-files"
    minio_secure: bool = False

    # ---------- etcd 配置中心 ----------
    etcd_endpoints: str = "127.0.0.1:2379"
    etcd_prefix: str = "/config"

    # ---------- Milvus ----------
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530
    milvus_collection: str = "rag_chunks"
    milvus_dim: int = 1024  # 默认 bge-m3 向量维度

    # ---------- 安全 ----------
    secret_key: str = "dev-only-change-me-0123456789abcdef0123456789abcdef"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    # ---------- CORS ----------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---------- 种子账户 ----------
    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin123"

    # ---------- 文件上传限制 ----------
    max_upload_mb: int = 50

    # ---------- 文档入库 ----------
    # inline=uvicorn 进程内后台解析（默认，不依赖额外进程，部署即用）
    # arq=投递 Redis 队列，需另行启动 `arq src.ingestion.tasks.WorkerSettings` 消费
    ingestion_mode: str = "inline"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
