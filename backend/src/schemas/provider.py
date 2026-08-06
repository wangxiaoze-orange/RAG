from typing import Any

from pydantic import BaseModel, Field


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="唯一标识（如 siliconflow）")
    provider_type: str = Field(description="qwen/deepseek/siliconflow/vllm/ollama/custom")
    base_url: str = Field(min_length=1, description="OpenAI 兼容地址")
    api_key: str = ""
    model: str = Field(description="默认对话模型")
    embedding_model: str | None = None
    rerank_model: str | None = None
    extra: dict[str, Any] = {}
    is_default: bool = False
    enabled: bool = True


class ProviderOut(BaseModel):
    name: str
    provider_type: str
    base_url: str
    api_key: str = ""  # 已脱敏（sk-****xxxx）
    model: str
    embedding_model: str | None = None
    rerank_model: str | None = None
    extra: dict[str, Any] = {}
    is_default: bool = False
    enabled: bool = True
    id: int | None = None
    api_key_set: bool = False  # 是否已保存 Key（供前端回显状态，Key 本身永不回传）


class TestIn(BaseModel):
    """连通测试请求：可选指定模型做真实对话试跑"""
    model: str | None = Field(default=None, description="指定对话模型试跑（留空仅测 /models 连通）")


class TestResult(BaseModel):
    ok: bool
    message: str = ""
    models: list[str] = []
