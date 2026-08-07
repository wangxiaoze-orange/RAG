"""流水线配置 API（管理员）：
- GET /api/v2/admin/config：返回全部可调参数的 当前值/默认值/说明/类型/分组
- PUT /api/v2/admin/config：批量写入（config_center 双写 etcd + MySQL，TTL 10 秒内生效）
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.config.config_center import config_center
from src.core.deps import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/admin/config", tags=["admin-config"])

# 配置项注册表：(键, 类型, 默认值, 说明, 分组)
CONFIG_ITEMS: list[tuple[str, str, object, str, str]] = [
    # 生成参数
    ("rag.temperature", "float", 0.7, "生成温度（0 严谨 ~ 2 发散）", "generate"),
    ("rag.rerank_top_n", "int", 6, "⑩ 重排后保留 Top N", "generate"),
    ("rag.rrf_top_k", "int", 15, "⑨ RRF 融合保留 Top N", "generate"),
    ("rag.compress_budget_tokens", "int", 3000, "⑪ 上下文压缩 token 预算", "generate"),
    # 缓存与经验库
    ("rag.feature.cache_enabled", "bool", True, "② 高频缓存总开关", "cache"),
    ("rag.feature.faq_enabled", "bool", True, "经验库（FAQ）直读与自动沉淀总开关", "cache"),
    ("rag.cache_freq_threshold", "int", 3, "② 防穿透：同一问题被问够 N 次后才读缓存", "cache"),
    ("rag.cache_write_min_freq", "int", 3, "⑯ 高频问题累计次数达标后写缓存/沉淀经验", "cache"),
    ("rag.cache_ttl_seconds", "int", 604800, "Redis 缓存 TTL（秒，默认 7 天）", "cache"),
    # 检索与置信度
    ("rag.feature.agent_retrieval_enabled", "bool", True, "⑦ ReAct 智能检索开关，关闭走规则路由", "retrieve"),
    ("rag.feature.web_search_enabled", "bool", True, "⑦ 网页检索开关（DuckDuckGo）", "retrieve"),
    ("rag.confidence_threshold", "float", 0.20, "⑫ 重排置信度阈值，低于则走常规兜底回答", "retrieve"),
    ("rag.reflection_threshold", "int", 0.4, "⑮ 自纠错审查分数阈值，低于则重生成一次", "retrieve"),
    ("rag.document_scope_chunk_budget", "int", 18, "⑤ 文档直读切片预算", "retrieve"),
    # 意图与召回配额
    ("rag.recall_total", "int", 20, "意图置信度加权的召回片段总量，按标签权重分配给各检索路", "intent"),
    ("rag.intent.label_weights", "json", None, "各意图标签权重（×标签置信度 → 各检索路召回配额占比）", "intent"),
    # 入库配置
    ("rag.parse_min_confidence", "float", 0.5, "解析模块默认置信度下限（知识库未单独配置时用）", "ingestion"),
    ("rag.chunk_strategy", "string", "markdown", "默认切片策略 markdown/fixed/semantic/parent_child", "ingestion"),
    # 其他
    ("rag.memory_ttl_days", "int", 30, "⑥ 显式记忆过期天数", "other"),
    ("rag.web_search_timeout_seconds", "int", 8, "网页检索超时秒", "other"),
]


class ConfigSetIn(BaseModel):
    values: dict[str, object]


def _type_check(key: str, type_: str, value: object) -> str:
    """类型校验并转为写入字符串"""
    if type_ == "bool":
        if not isinstance(value, bool):
            raise HTTPException(status_code=400, detail=f"{key} 需要布尔值")
        return "true" if value else "false"
    if type_ == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise HTTPException(status_code=400, detail=f"{key} 需要整数")
        return str(value)
    if type_ == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(status_code=400, detail=f"{key} 需要数值")
        return str(value)
    if type_ == "json":
        return json.dumps(value, ensure_ascii=False)
    return str(value)


@router.get("")
async def get_config(admin: dict = Depends(require_admin)) -> list[dict]:
    """返回全部配置项：键/类型/默认值/当前值/说明/分组"""
    out = []
    for key, type_, default, desc, group in CONFIG_ITEMS:
        if type_ == "bool":
            current = await config_center.get_bool(key, bool(default))
        elif type_ == "int":
            current = await config_center.get_int(key, int(default)) if isinstance(default, int) else await config_center.get_raw(key)
        elif type_ == "float":
            current = await config_center.get_float(key, float(default)) if isinstance(default, (int, float)) else await config_center.get_raw(key)
        elif type_ == "json":
            current = await config_center.get_json(key, default)
        else:
            current = await config_center.get(key, str(default or ""))
        out.append({
            "key": key,
            "type": type_,
            "default": default,
            "value": current,
            "desc": desc,
            "group": group,
        })
    return out


@router.put("")
async def set_config(body: ConfigSetIn, admin: dict = Depends(require_admin)) -> dict:
    """批量写入配置（etcd + MySQL 双写）"""
    registry = {k: t for k, t, *_ in CONFIG_ITEMS}
    written = 0
    for key, value in body.values.items():
        type_ = registry.get(key)
        if type_ is None:
            raise HTTPException(status_code=400, detail=f"未知配置键: {key}")
        raw = _type_check(key, type_, value)
        await config_center.set(key, raw)
        written += 1
        logger.info("配置更新: %s = %s（操作人 %s）", key, raw, admin["username"])
    return {"ok": True, "written": written}
