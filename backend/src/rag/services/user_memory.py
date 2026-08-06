"""用户显式记忆：Redis 存储，TTL 30 天（可配）
⑥ 显式记忆抽取：正则匹配"我喜欢/我不喜欢/我对X过敏/请用X回答/叫我X" → 写入
"""
import json
import logging
import re
from datetime import datetime

from src.config.config_center import config_center
from src.db.redis import get_redis

logger = logging.getLogger(__name__)

MEMORY_TTL_DAYS = 30
MAX_MEMORIES = 50  # 每人最多保留条数

# ⑥ 显式记忆抽取正则：类型 → 正则
EXPLICIT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("preference", re.compile(r"我喜欢(.{1,60}?)(?:[，。！？,.!?；;]|$)")),
    ("dislike", re.compile(r"我不喜欢(.{1,60}?)(?:[，。！？,.!?；;]|$)")),
    ("allergy", re.compile(r"我对(.{1,60}?)过敏")),
    ("style", re.compile(r"请用(.{1,60}?)回答|以后(?:都)?用(.{1,60}?)回答")),
    ("name", re.compile(r"叫我(.{1,20}?)(?:吧|就行|就可以|$)|我的名字是(.{1,20}?)(?:[，。！？,!?；;]|$)")),
]


def extract_explicit_memories(question: str) -> list[dict]:
    """从问题中抽取显式记忆，返回 [{type, content}]"""
    found: list[dict] = []
    for mtype, pattern in EXPLICIT_PATTERNS:
        for m in pattern.finditer(question):
            content = next((g for g in m.groups() if g and g.strip()), None)
            if content:
                found.append({"type": mtype, "content": content.strip()})
    return found


def _key(user_id: int) -> str:
    return f"rag:memory:{user_id}"


async def add_memory(user_id: int, mtype: str, content: str) -> None:
    """写入一条记忆（LPUSH 头部 + TTL 滑动刷新 + 条数上限）"""
    ttl_days = await config_center.get_int("rag.memory_ttl_days", MEMORY_TTL_DAYS)
    redis = get_redis()
    item = {
        "type": mtype,
        "content": content,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    key = _key(user_id)
    await redis.lpush(key, json.dumps(item, ensure_ascii=False))
    await redis.ltrim(key, 0, MAX_MEMORIES - 1)
    await redis.expire(key, ttl_days * 86400)


async def list_memories(user_id: int, keyword: str | None = None) -> list[dict]:
    """列出用户记忆，可按关键词过滤"""
    redis = get_redis()
    raw_list = await redis.lrange(_key(user_id), 0, -1)
    memories = [json.loads(r) for r in raw_list if r]
    if keyword:
        memories = [m for m in memories if keyword.lower() in m.get("content", "").lower()]
    return memories


async def save_explicit_from_question(user_id: int, question: str) -> list[dict]:
    """⑥ 抽取并保存显式记忆，返回本次新保存的条目"""
    saved = []
    for mem in extract_explicit_memories(question):
        await add_memory(user_id, mem["type"], mem["content"])
        saved.append(mem)
    if saved:
        logger.info("用户 %d 显式记忆保存 %d 条: %s", user_id, len(saved), saved)
    return saved
