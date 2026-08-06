"""模型供应商数据模型与默认配置"""
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProviderType(str, Enum):
    """支持的供应商类型（全部走 OpenAI 兼容接口）"""

    QWEN = "qwen"            # 通义千问 DashScope 兼容模式
    DEEPSEEK = "deepseek"
    SILICONFLOW = "siliconflow"
    VLLM = "vllm"            # 本地 vLLM
    OLLAMA = "ollama"        # 本地 Ollama
    CUSTOM = "custom"


@dataclass
class ProviderConfig:
    """一个供应商的完整配置（etcd /config/providers/{name} 为主存储，MySQL 兜底）"""

    name: str
    provider_type: str
    base_url: str
    api_key: str = ""
    model: str = ""
    embedding_model: str | None = None
    rerank_model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    is_default: bool = False
    enabled: bool = True
    id: int | None = None

    # ---------- 序列化 ----------
    def to_dict(self, mask_key: bool = True) -> dict:
        d = {
            "name": self.name,
            "provider_type": self.provider_type,
            "base_url": self.base_url,
            "api_key": mask_api_key(self.api_key) if mask_key else self.api_key,
            "model": self.model,
            "embedding_model": self.embedding_model,
            "rerank_model": self.rerank_model,
            "extra": self.extra,
            "is_default": self.is_default,
            "enabled": self.enabled,
            "id": self.id,
        }
        return d

    def to_json(self, mask_key: bool = True) -> str:
        return json.dumps(self.to_dict(mask_key=mask_key), ensure_ascii=False)

    @classmethod
    def from_json(cls, name: str, raw: str) -> "ProviderConfig":
        data = json.loads(raw)
        return cls(
            name=name,
            provider_type=data.get("provider_type", "custom"),
            base_url=data.get("base_url", ""),
            api_key=data.get("api_key", ""),
            model=data.get("model", ""),
            embedding_model=data.get("embedding_model"),
            rerank_model=data.get("rerank_model"),
            extra=data.get("extra") or {},
            is_default=bool(data.get("is_default", False)),
            enabled=bool(data.get("enabled", True)),
            id=data.get("id"),
        )


def mask_api_key(key: str) -> str:
    """出参脱敏：sk-****xxxx"""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:3]}****{key[-4:]}"
