from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import load_config, mask_api_key, save_config, reload_config
from app.config import Settings, ProviderConfig, ModelInfo

router = APIRouter()


class SettingsUpdateRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    default_model: Optional[str] = None
    default_provider: Optional[str] = None
    max_iterations: Optional[int] = None
    auto_approve: Optional[bool] = None
    screenshot_on_step: Optional[bool] = None


class ProviderUpdateRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    base_url: str
    api_key: str
    models: list[dict]


class NewProviderRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    name: str
    base_url: str
    api_key: str
    models: list[dict] = []


@router.get("/api/settings")
def get_settings():
    """返回所有 Provider（含脱敏 API Key）+ 全局设置"""
    cfg = load_config()
    providers = {}
    for pname, p in cfg.providers.items():
        raw_key = getattr(p, '_raw_api_key', '') or p.api_key
        providers[pname] = {
            "name": pname,
            "base_url": p.base_url,
            "api_key_masked": mask_api_key(raw_key),
            "models": [m.model_dump() for m in p.models],
        }
    return {
        "providers": providers,
        "settings": cfg.settings.model_dump(),
    }


@router.put("/api/settings")
def update_settings(req: SettingsUpdateRequest):
    """部分更新全局设置"""
    cfg = load_config()
    update = req.model_dump(exclude_none=True)
    current = cfg.settings.model_dump()
    current.update(update)
    cfg.settings = Settings(**current)
    save_config(cfg)
    return {"status": "ok"}


@router.put("/api/providers/{provider_name}")
def update_provider(provider_name: str, req: ProviderUpdateRequest):
    """更新指定 Provider 的配置"""
    cfg = load_config()
    old_raw = getattr(cfg.providers.get(provider_name, None), '_raw_api_key', '') if provider_name in cfg.providers else ''
    # 如果请求中的 api_key 与被脱敏前的值不同，说明用户改了 key
    cfg.providers[provider_name] = ProviderConfig(
        base_url=req.base_url,
        api_key=req.api_key,
        models=[ModelInfo(**m) for m in req.models],
    )
    # 如果用户输入了新的 api_key（非空），则使用新值；否则保留旧值（支持 env var 语法）
    cfg.providers[provider_name]._raw_api_key = req.api_key if req.api_key else old_raw
    save_config(cfg)
    return {"status": "ok"}


@router.post("/api/providers")
def create_provider(req: NewProviderRequest):
    """创建新的 Provider"""
    cfg = load_config()
    if req.name in cfg.providers:
        raise HTTPException(status_code=409, detail=f"Provider '{req.name}' already exists")
    cfg.providers[req.name] = ProviderConfig(
        base_url=req.base_url,
        api_key=req.api_key,
        models=[ModelInfo(**m) for m in req.models],
    )
    cfg.providers[req.name]._raw_api_key = req.api_key
    save_config(cfg)
    return {"status": "ok"}


@router.delete("/api/providers/{provider_name}")
def delete_provider(provider_name: str):
    """删除 Provider（拒绝删除 default_provider）"""
    cfg = load_config()
    if provider_name not in cfg.providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")
    if cfg.settings.default_provider == provider_name:
        raise HTTPException(status_code=400, detail="Cannot delete the default provider. Change the default first.")
    del cfg.providers[provider_name]
    save_config(cfg)
    return {"status": "ok"}


@router.post("/api/config/reload")
def force_config_reload():
    """强制刷新后端配置缓存"""
    cfg = reload_config()
    return {"status": "ok", "default_model": cfg.settings.default_model}
