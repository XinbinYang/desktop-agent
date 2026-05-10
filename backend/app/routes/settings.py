import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
import httpx
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
    sandbox_mode: Optional[str] = None


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


class ProviderTestRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    provider_name: Optional[str] = None
    base_url: str
    api_key: str = ""
    model_id: Optional[str] = None


def _resolve_api_key(raw_key: str) -> str:
    key = raw_key.strip()
    if key.startswith("${") and key.endswith("}"):
        return os.environ.get(key[2:-1], "")
    return key


def _is_local_provider(provider_name: str | None, base_url: str) -> bool:
    lowered_name = (provider_name or "").lower()
    lowered_url = base_url.lower()
    return (
        lowered_name in {"local", "ollama"}
        or "localhost" in lowered_url
        or "127.0.0.1" in lowered_url
        or lowered_url.startswith("http://[::1]")
    )


def _extract_model_ids(payload: dict[str, Any]) -> list[str]:
    raw_models = payload.get("data")
    if raw_models is None:
        raw_models = payload.get("models")
    if not isinstance(raw_models, list):
        return []

    ids: list[str] = []
    for item in raw_models:
        if isinstance(item, dict):
            model_id = item.get("id") or item.get("name")
        else:
            model_id = str(item)
        if model_id:
            ids.append(str(model_id))
    return ids


async def _fetch_provider_models(provider_name: str | None, base_url: str, api_key: str) -> tuple[int, dict[str, Any]]:
    url = base_url.rstrip("/") + "/models"
    lowered = (provider_name or "").lower() + " " + base_url.lower()
    headers: dict[str, str] = {}
    if "anthropic" in lowered:
        headers["anthropic-version"] = "2023-06-01"
        if api_key:
            headers["x-api-key"] = api_key
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(url, headers=headers)
    try:
        payload = response.json()
    except ValueError:
        payload = {"text": response.text[:500]}
    return response.status_code, payload


def _connection_message_for_status(status_code: int) -> str:
    if status_code in {401, 403}:
        return "API Key 无效或没有访问权限"
    if status_code == 404:
        return "Base URL 不支持 /models，请检查地址是否包含正确的 v1 路径"
    return f"Provider 返回 HTTP {status_code}"


@router.get("/api/settings")
def get_settings():
    """返回所有 Provider（含脱敏 API Key）+ 全局设置"""
    cfg = load_config()
    providers = {}
    for pname, p in cfg.providers.items():
        raw_key = p._raw_api_key or p.api_key
        providers[pname] = {
            "name": pname,
            "base_url": p.base_url,
            "api_key_masked": mask_api_key(raw_key),
            "api_key_configured": bool(p.api_key) or _is_local_provider(pname, p.base_url),
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
    old_raw = cfg.providers[provider_name]._raw_api_key if provider_name in cfg.providers else ""
    cfg.providers[provider_name] = ProviderConfig(
        base_url=req.base_url,
        api_key=req.api_key,
        models=[ModelInfo(**m) for m in req.models],
    )
    # Empty incoming api_key means "keep existing"; preserve env-var syntax via _raw_api_key.
    cfg.providers[provider_name]._raw_api_key = req.api_key if req.api_key else old_raw
    save_config(cfg)
    return {"status": "ok"}


@router.post("/api/providers/test")
async def test_provider_connection(req: ProviderTestRequest):
    """Test provider connectivity without returning or logging API keys."""
    cfg = load_config()
    provider_name = (req.provider_name or "").strip() or None
    base_url = req.base_url.strip()
    if not base_url:
        return {"ok": False, "message": "Base URL 不能为空"}

    api_key = _resolve_api_key(req.api_key)
    if not api_key and provider_name and provider_name in cfg.providers:
        api_key = cfg.providers[provider_name].api_key

    if not api_key and not _is_local_provider(provider_name, base_url):
        return {"ok": False, "message": "请先填写 API Key 或配置对应环境变量"}

    try:
        status_code, payload = await _fetch_provider_models(provider_name, base_url, api_key)
    except httpx.TimeoutException:
        return {"ok": False, "message": "连接超时，请检查网络、代理或 Base URL"}
    except httpx.RequestError as exc:
        return {"ok": False, "message": f"连接失败: {exc.__class__.__name__}"}

    if status_code >= 400:
        return {
            "ok": False,
            "message": _connection_message_for_status(status_code),
            "status_code": status_code,
        }

    model_ids = _extract_model_ids(payload)
    model_id = (req.model_id or "").strip()
    model_found = model_id in model_ids if model_id and model_ids else None
    if model_id and model_ids and not model_found:
        return {
            "ok": False,
            "message": f"连接成功，但服务未返回模型 {model_id}",
            "status_code": status_code,
            "model_found": False,
            "model_count": len(model_ids),
        }

    return {
        "ok": True,
        "message": "连接成功",
        "status_code": status_code,
        "model_found": model_found,
        "model_count": len(model_ids),
    }


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
