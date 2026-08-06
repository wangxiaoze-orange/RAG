"""模型供应商 API：增删改查 / 连通性测试 / 切换默认"""
import httpx
from fastapi import APIRouter, Depends, HTTPException

from src.core.deps import get_current_user, get_provider_manager
from src.providers.base import ProviderConfig
from src.providers.manager import ProviderManager
from src.schemas.provider import ProviderIn, ProviderOut, TestIn, TestResult

router = APIRouter(prefix="/api/v2/providers", tags=["providers"])


def _out(cfg: ProviderConfig) -> ProviderOut:
    """转响应模型：api_key 已脱敏，另附 api_key_set 标记供前端回显「已配置」状态"""
    return ProviderOut(**cfg.to_dict(), api_key_set=bool(cfg.api_key))


@router.get("", response_model=list[ProviderOut])
async def list_providers(
    _user: dict = Depends(get_current_user),
    pm: ProviderManager = Depends(get_provider_manager),
) -> list[ProviderOut]:
    return [_out(p) for p in await pm.list_providers(force=True)]


@router.post("", response_model=ProviderOut)
async def create_provider(
    body: ProviderIn,
    _user: dict = Depends(get_current_user),
    pm: ProviderManager = Depends(get_provider_manager),
) -> ProviderOut:
    existing = await pm.get(body.name)
    if existing is not None:
        raise HTTPException(status_code=409, detail="供应商名称已存在")
    cfg = ProviderConfig(
        name=body.name,
        provider_type=body.provider_type,
        base_url=body.base_url,
        api_key=body.api_key,
        model=body.model,
        embedding_model=body.embedding_model,
        rerank_model=body.rerank_model,
        extra=body.extra or {},
        is_default=body.is_default,
        enabled=body.enabled,
    )
    await pm.upsert(cfg)
    return _out(cfg)


@router.put("/{name}", response_model=ProviderOut)
async def update_provider(
    name: str,
    body: ProviderIn,
    _user: dict = Depends(get_current_user),
    pm: ProviderManager = Depends(get_provider_manager),
) -> ProviderOut:
    cfg = await pm.get(name)
    if cfg is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    # api_key 留空表示不修改
    cfg.provider_type = body.provider_type
    cfg.base_url = body.base_url
    if body.api_key:
        cfg.api_key = body.api_key
    cfg.model = body.model
    cfg.embedding_model = body.embedding_model
    cfg.rerank_model = body.rerank_model
    cfg.extra = body.extra or {}
    cfg.is_default = body.is_default
    cfg.enabled = body.enabled
    await pm.upsert(cfg)
    return _out(cfg)


@router.delete("/{name}")
async def delete_provider(
    name: str,
    _user: dict = Depends(get_current_user),
    pm: ProviderManager = Depends(get_provider_manager),
) -> dict:
    cfg = await pm.get(name)
    if cfg is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    await pm.delete(name)
    return {"ok": True}


@router.post("/{name}/default")
async def set_default_provider(
    name: str,
    _user: dict = Depends(get_current_user),
    pm: ProviderManager = Depends(get_provider_manager),
) -> dict:
    cfg = await pm.get(name)
    if cfg is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    await pm.set_default(name)
    return {"ok": True}


@router.post("/{name}/test", response_model=TestResult)
async def test_provider(
    name: str,
    body: TestIn | None = None,
    _user: dict = Depends(get_current_user),
    pm: ProviderManager = Depends(get_provider_manager),
) -> TestResult:
    cfg = await pm.get(name)
    if cfg is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    model = body.model if body else None
    try:
        result = await pm.test_connection(cfg, model=model)
    except httpx.HTTPStatusError as e:
        return TestResult(ok=False, message=f"HTTP {e.response.status_code}: {e.response.text[:200]}")
    except Exception as e:  # noqa: BLE001
        return TestResult(ok=False, message=str(e))
    if model:
        return TestResult(ok=True, message=f"连通正常，模型 {model} 试跑成功", models=result["models"])
    return TestResult(ok=True, message="连通正常", models=result["models"])
