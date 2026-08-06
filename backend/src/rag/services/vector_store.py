"""Milvus 向量存储：集合管理 / 写入 / 检索 / 按文档删除
集合 rag_chunks：chunk_id(VARCHAR 主键) / doc_id / kb_id / doc_name / page_number / section_title / content / embedding
"""
import asyncio
import logging
from functools import lru_cache
from typing import Any

from pymilvus import DataType, MilvusClient

from src.config.settings import settings

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self) -> None:
        self.client = MilvusClient(uri=f"http://{settings.milvus_host}:{settings.milvus_port}")
        self.collection = settings.milvus_collection
        self.dim = settings.milvus_dim

    # ---------- 集合管理 ----------
    def _ensure_collection(self) -> None:
        if self.client.has_collection(self.collection):
            return
        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("chunk_id", DataType.VARCHAR, max_length=64, is_primary=True)
        schema.add_field("doc_id", DataType.INT64)
        schema.add_field("kb_id", DataType.INT64)
        schema.add_field("doc_name", DataType.VARCHAR, max_length=255)
        schema.add_field("page_number", DataType.INT64)
        schema.add_field("section_title", DataType.VARCHAR, max_length=255)
        schema.add_field("content", DataType.VARCHAR, max_length=65535)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.dim)
        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        self.client.create_collection(self.collection, schema=schema, index_params=index_params)
        logger.info("Milvus 集合 %s 已创建（dim=%d）", self.collection, self.dim)

    async def ensure_collection(self) -> None:
        await asyncio.to_thread(self._ensure_collection)

    # ---------- 写入 ----------
    async def insert_chunks(self, rows: list[dict[str, Any]]) -> None:
        """rows: [{chunk_id(str), doc_id, kb_id, doc_name, page_number, section_title, content, embedding}]"""
        if not rows:
            return
        await self.ensure_collection()

        def _insert() -> None:
            # Milvus 标量 INT64 字段不接受 None（整列传 nil 会被拒绝），空页码统一落 0
            normalized = []
            for r in rows:
                if r.get("page_number") is None:
                    r = dict(r)
                    r["page_number"] = 0
                normalized.append(r)
            self.client.insert(self.collection, normalized)
        await asyncio.to_thread(_insert)
        logger.info("Milvus 写入 %d 条切片", len(rows))

    # ---------- 检索 ----------
    async def search(
        self,
        query_embedding: list[float],
        kb_ids: list[int] | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """语义检索（余弦相似度），返回结果按相似度降序"""
        expr = ""
        if kb_ids:
            expr = f"kb_id in [{', '.join(str(k) for k in kb_ids)}]"

        def _search() -> list[dict[str, Any]]:
            results = self.client.search(
                collection_name=self.collection,
                data=[query_embedding],
                limit=top_k,
                filter=expr or None,
                output_fields=["chunk_id", "doc_id", "kb_id", "doc_name", "content", "page_number", "section_title"],
            )
            hits = results[0] if results else []
            out = []
            for rank, hit in enumerate(hits, start=1):
                ent = hit.get("entity") or {}
                out.append(
                    {
                        "chunk_id": str(ent.get("chunk_id") or ""),  # 主键是 "doc_序号" 字符串，勿转 int
                        "doc_id": int(ent.get("doc_id", 0)),
                        "kb_id": int(ent.get("kb_id", 0)),
                        "doc_name": ent.get("doc_name", ""),
                        "content": ent.get("content", ""),
                        "page_number": ent.get("page_number") or None,
                        "section_title": ent.get("section_title") or None,
                        "score": round(float(hit.get("distance", 0.0)), 4),
                        "source_type": "vector",
                        "rank": rank,
                    }
                )
            return out

        try:
            return await asyncio.to_thread(_search)
        except Exception as e:  # noqa: BLE001
            logger.warning("Milvus 检索失败（向量路为空）: %s", e)
            return []

    # ---------- 删除 ----------
    async def delete_by_doc(self, doc_id: int) -> None:
        def _delete() -> None:
            if not self.client.has_collection(self.collection):
                return
            self.client.delete(self.collection, filter=f"doc_id == {doc_id}")
        try:
            await asyncio.to_thread(_delete)
            logger.info("Milvus 删除 doc_id=%d 全部切片", doc_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("Milvus 删除失败 doc_id=%d: %s", doc_id, e)


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    return VectorStore()
