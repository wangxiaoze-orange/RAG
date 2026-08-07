"""父子切片扩展：检索命中的子块若带 parent_id，则替换为父块全文
- 子块 chunk_id 形如 "{doc_id}_{index}"，据此反查 KbChunk.parent_id
- 同一父块被多个子块命中时去重，保留得分最高的一条
- 无父块关系时原样返回（幂等，可安全重复调用）
"""
import logging

from sqlalchemy import and_, or_, select

from src.db.models import KbChunk
from src.db.session import async_session_maker

logger = logging.getLogger(__name__)


def _parse_chunk_key(chunk: dict) -> tuple[int, int] | None:
    """从 chunk_id "{doc_id}_{index}" 解析出 (doc_id, chunk_index)"""
    cid = str(chunk.get("chunk_id") or "")
    if "_" not in cid:
        return None
    try:
        doc_id = int(chunk.get("doc_id") or cid.split("_", 1)[0])
        idx = int(cid.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        return None
    return doc_id, idx


async def expand_parents(chunks: list[dict]) -> list[dict]:
    """将带父块的子块内容替换为父块全文；同父块去重保留最高分"""
    if not chunks:
        return chunks

    keys = [k for k in (_parse_chunk_key(c) for c in chunks) if k]
    if not keys:
        return chunks

    async with async_session_maker() as session:
        conds = [and_(KbChunk.doc_id == d, KbChunk.chunk_index == i) for d, i in set(keys)]
        rows = (await session.execute(select(KbChunk).where(or_(*conds)))).scalars().all()
        parent_id_of = {(r.doc_id, r.chunk_index): r.parent_id for r in rows if r.parent_id}
        if not parent_id_of:
            return chunks
        parent_ids = list(set(parent_id_of.values()))
        parents = {
            p.id: p
            for p in (
                await session.execute(select(KbChunk).where(KbChunk.id.in_(parent_ids)))
            ).scalars().all()
        }

    out: list[dict] = []
    seen_parent: dict[int, int] = {}  # parent_id → out 中下标
    expanded = 0
    for chunk in chunks:
        key = _parse_chunk_key(chunk)
        pid = parent_id_of.get(key) if key else None
        parent = parents.get(pid) if pid else None
        if parent is None:
            out.append(chunk)
            continue
        new = dict(chunk)
        new["content"] = parent.content
        new["token_count"] = parent.token_count
        new["expanded_parent"] = True
        if pid in seen_parent:
            # 同父块去重：保留得分更高的一条
            prev = out[seen_parent[pid]]
            if float(new.get("score", 0.0)) > float(prev.get("score", 0.0)):
                out[seen_parent[pid]] = new
        else:
            seen_parent[pid] = len(out)
            out.append(new)
            expanded += 1
    if expanded:
        logger.info("父块扩展：%d 条子块 → %d 条（父块去重后）", len(chunks), len(out))
    return out
