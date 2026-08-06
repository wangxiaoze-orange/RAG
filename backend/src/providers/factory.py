"""供应商工厂：把 ProviderConfig 变成可用的 LLM / Embedding 客户端（OpenAI 兼容）"""
import logging
from typing import Iterable

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from src.providers.base import ProviderConfig

logger = logging.getLogger(__name__)


def create_chat_llm(
    cfg: ProviderConfig,
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    **kwargs,
) -> ChatOpenAI:
    """创建对话 LLM（langchain-openai 1.x 起 ChatOpenAI 原生支持异步 ainvoke/astream）"""
    headers = dict(cfg.extra.get("headers") or {})
    return ChatOpenAI(
        base_url=cfg.base_url.rstrip("/") + "/",
        api_key=cfg.api_key or "EMPTY",
        model=model or cfg.model,
        temperature=temperature,
        max_tokens=max_tokens,
        default_headers=headers or None,
        **kwargs,
    )


def create_embeddings(
    cfg: ProviderConfig,
    *,
    model: str | None = None,
) -> OpenAIEmbeddings:
    """创建嵌入客户端（默认硅基流动 BAAI/bge-m3，1024 维）"""
    return OpenAIEmbeddings(
        base_url=cfg.base_url.rstrip("/") + "/",
        api_key=cfg.api_key or "EMPTY",
        model=model or cfg.embedding_model or "BAAI/bge-m3",
        check_embedding_ctx_length=False,
        chunk_size=32,
    )


async def embed_texts(cfg: ProviderConfig, texts: Iterable[str], model: str | None = None) -> list[list[float]]:
    """批量嵌入文本，返回向量列表"""
    emb = create_embeddings(cfg, model=model)
    return await emb.aembed_documents(list(texts))
