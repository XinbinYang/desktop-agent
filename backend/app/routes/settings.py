import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
import httpx
from pydantic import BaseModel

from app.config import load_config, mask_api_key, save_config, reload_config
from app.config import Settings, ProviderConfig, ModelInfo, CodingAgentConfig, PersonalAgentConfig, WebSearchConfig
from app.roles import RoleManager
from app.skills import SkillManager
from app.tools.web_tool import perform_web_search

router = APIRouter()


class SettingsUpdateRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    default_model: Optional[str] = None
    default_provider: Optional[str] = None
    max_iterations: Optional[int] = None
    auto_approve: Optional[bool] = None
    screenshot_on_step: Optional[bool] = None
    sandbox_mode: Optional[str] = None
    thinking_intensity_default: Optional[str] = None
    thinking_policy_by_provider: Optional[dict[str, dict[str, Any]]] = None
    collaboration_mode: Optional[str] = None
    max_parallel_agents: Optional[int] = None
    review_gate_enabled: Optional[bool] = None
    coding_agent: Optional[dict[str, Any]] = None
    personal_agent: Optional[dict[str, Any]] = None
    auto_approve_rules: Optional[list[dict[str, Any]]] = None


class ProviderUpdateRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    base_url: str
    api_key: str
    litellm_provider: str = ""
    models: list[dict]


class NewProviderRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    name: str
    base_url: str
    api_key: str
    litellm_provider: str = ""
    models: list[dict] = []


class ProviderTestRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    provider_name: Optional[str] = None
    base_url: str
    api_key: str = ""
    model_id: Optional[str] = None


class RenameProviderRequest(BaseModel):
    new_name: str


class FetchModelsRequest(BaseModel):
    provider_name: Optional[str] = None
    base_url: str
    api_key: str = ""


class WebSearchSettingsRequest(BaseModel):
    provider: Optional[str] = None
    brave_api_key: Optional[str] = None
    tavily_api_key: Optional[str] = None
    serpapi_api_key: Optional[str] = None
    fallback_enabled: Optional[bool] = None
    allow_private_network: Optional[bool] = None


class WebSearchTestRequest(WebSearchSettingsRequest):
    query: str = "OpenAI API documentation"


class SuggestedModel(BaseModel):
    id: str
    suggested_name: str
    suggested_context: int
    vision: bool


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


def _web_search_settings_payload(cfg) -> dict[str, Any]:
    web = cfg.web_search
    return {
        "provider": web.provider,
        "fallback_enabled": web.fallback_enabled,
        "allow_private_network": web.allow_private_network,
        "providers": {
            "brave": {
                "api_key_masked": mask_api_key(web._raw_brave_api_key or web.brave_api_key),
                "api_key_configured": bool(web.brave_api_key),
            },
            "tavily": {
                "api_key_masked": mask_api_key(web._raw_tavily_api_key or web.tavily_api_key),
                "api_key_configured": bool(web.tavily_api_key),
            },
            "serpapi": {
                "api_key_masked": mask_api_key(web._raw_serpapi_api_key or web.serpapi_api_key),
                "api_key_configured": bool(web.serpapi_api_key),
            },
        },
    }


def _apply_web_search_update(web: WebSearchConfig, req: WebSearchSettingsRequest) -> WebSearchConfig:
    current = web.model_dump()
    update = req.model_dump(exclude_none=True)
    provider = update.get("provider")
    if provider:
        provider = str(provider).lower()
        if provider not in {"auto", "brave", "tavily", "serpapi", "duckduckgo"}:
            raise HTTPException(status_code=400, detail=f"Unknown web search provider: {provider}")
        current["provider"] = provider
    for field in ("fallback_enabled", "allow_private_network"):
        if field in update:
            current[field] = bool(update[field])

    raw_values = {
        "brave_api_key": web._raw_brave_api_key,
        "tavily_api_key": web._raw_tavily_api_key,
        "serpapi_api_key": web._raw_serpapi_api_key,
    }
    for field in raw_values:
        value = update.get(field)
        if isinstance(value, str) and value.strip():
            current[field] = _resolve_api_key(value)
            raw_values[field] = value.strip()

    next_web = WebSearchConfig(**current)
    next_web._raw_brave_api_key = raw_values["brave_api_key"]
    next_web._raw_tavily_api_key = raw_values["tavily_api_key"]
    next_web._raw_serpapi_api_key = raw_values["serpapi_api_key"]
    return next_web


# ---- Model ID hint table for auto-populating context / vision / name ----
_MODEL_HINTS: list[tuple[list[str], int, bool, str]] = [
    (["gpt-4o", "chatgpt-4o"], 128000, True, "GPT-4o"),
    (["gpt-4o-mini"], 128000, True, "GPT-4o Mini"),
    (["gpt-4-turbo"], 128000, True, "GPT-4 Turbo"),
    (["gpt-4"], 8192, False, "GPT-4"),
    (["gpt-3.5-turbo"], 16384, False, "GPT-3.5 Turbo"),
    (["o1", "o1-"], 200000, False, "o1"),
    (["o3-mini"], 200000, False, "o3 Mini"),
    (["claude-3-5-sonnet"], 200000, True, "Claude 3.5 Sonnet"),
    (["claude-3-5-haiku"], 200000, True, "Claude 3.5 Haiku"),
    (["claude-3-opus"], 200000, True, "Claude 3 Opus"),
    (["claude-4-sonnet", "claude-sonnet-4"], 200000, True, "Claude Sonnet 4"),
    (["deepseek-reasoner", "deepseek-r1", "deepseek-r1-distill"], 65536, False, "DeepSeek Reasoner"),
    (["deepseek-v4-pro"], 1048576, False, "DeepSeek V4 Pro"),
    (["deepseek-v4-flash"], 1048576, False, "DeepSeek V4 Flash"),
    (["deepseek-chat", "deepseek-v3"], 65536, False, "DeepSeek V3"),
    (["gemini-2.0-flash", "gemini-2.5"], 1048576, True, "Gemini"),
    (["mistral-large"], 128000, False, "Mistral Large"),
    (["codestral"], 256000, False, "Codestral"),
    (["llama-3.1"], 131072, False, "Llama 3.1"),
    (["qwen-2.5"], 131072, True, "Qwen 2.5"),
    (["command-r"], 128000, False, "Command R"),
    # Broad catchall: any other DeepSeek model (older series)
    (["deepseek-"], 65536, False, "DeepSeek"),
]


def _suggest_model_metadata(model_id: str) -> dict:
    """Infer display name, context window, and vision support from model ID."""
    lower = model_id.lower()
    for prefixes, ctx, vision, name in _MODEL_HINTS:
        for prefix in prefixes:
            if lower.startswith(prefix):
                return {
                    "id": model_id,
                    "suggested_name": name,
                    "suggested_context": ctx,
                    "vision": vision,
                }
    # Fallback: derive name from the id (capitalize after hyphens/slashes)
    fallback_name = model_id.split("/")[-1].replace("-", " ").title()
    return {
        "id": model_id,
        "suggested_name": fallback_name,
        "suggested_context": 32000,
        "vision": False,
    }


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


def _clamp_parallel_agent_count(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 3
    return max(1, min(16, parsed))


async def _fetch_provider_models(provider_name: str | None, base_url: str, api_key: str) -> tuple[int, dict[str, Any]]:
    lowered = (provider_name or "").lower() + " " + base_url.lower()
    if "kimi" in lowered and "/coding" in base_url.lower():
        base = base_url.rstrip("/")
        for suffix in ("/chat/completions", "/v1/messages", "/messages", "/models"):
            if base.endswith(suffix):
                base = base[: -len(suffix)].rstrip("/")
                break
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        url = f"{base}/models"
    else:
        url = base_url.rstrip("/") + "/models"
    headers: dict[str, str] = {}
    if "kimi" in lowered and "/coding" in base_url.lower():
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    elif "anthropic" in lowered:
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
    try:
        cfg = load_config()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"无法读取模型配置文件（models.yaml）：{e}",
        ) from e
    providers = {}
    for pname, p in cfg.providers.items():
        raw_key = p._raw_api_key or p.api_key
        providers[pname] = {
            "name": pname,
            "base_url": p.base_url,
            "api_key_masked": mask_api_key(raw_key),
            "api_key_configured": bool(p.api_key) or _is_local_provider(pname, p.base_url),
            "litellm_provider": p.litellm_provider,
            "models": [m.model_dump() for m in p.models],
        }
    return {
        "providers": providers,
        "settings": cfg.settings.model_dump(),
        "coding_agent": cfg.coding_agent.model_dump(),
        "personal_agent": cfg.personal_agent.model_dump(),
        "web_search": _web_search_settings_payload(cfg),
    }


@router.put("/api/settings")
def update_settings(req: SettingsUpdateRequest):
    """部分更新全局设置"""
    cfg = load_config()
    update = req.model_dump(exclude_none=True)
    coding_update = update.pop("coding_agent", None)
    personal_update = update.pop("personal_agent", None)
    current = cfg.settings.model_dump()
    if "max_parallel_agents" in update:
        update["max_parallel_agents"] = _clamp_parallel_agent_count(update["max_parallel_agents"])
    current.update(update)
    cfg.settings = Settings(**current)
    if isinstance(coding_update, dict):
        if "max_parallel_workers" in coding_update:
            coding_update["max_parallel_workers"] = _clamp_parallel_agent_count(coding_update["max_parallel_workers"])
        coding_current = cfg.coding_agent.model_dump()
        coding_current.update(coding_update)
        cfg.coding_agent = CodingAgentConfig(**coding_current)
    if isinstance(personal_update, dict):
        personal_current = cfg.personal_agent.model_dump()
        personal_current.update(personal_update)
        cfg.personal_agent = PersonalAgentConfig(**personal_current)
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
        litellm_provider=req.litellm_provider,
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


@router.post("/api/providers/{provider_name}/rename")
def rename_provider(provider_name: str, req: RenameProviderRequest):
    """Rename a provider, updating all model references and default_provider."""
    new_name = req.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="新名称不能为空")
    if new_name == provider_name:
        raise HTTPException(status_code=400, detail="新旧名称相同")
    cfg = load_config()
    if provider_name not in cfg.providers:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' 不存在")
    if new_name in cfg.providers:
        raise HTTPException(status_code=409, detail=f"Provider '{new_name}' 已存在")

    # Move the provider config to the new key
    provider = cfg.providers.pop(provider_name)
    # Update model provider reference
    for m in provider.models:
        m.provider = new_name
    cfg.providers[new_name] = provider

    # Update default_provider if it pointed to the old name
    if cfg.settings.default_provider == provider_name:
        cfg.settings.default_provider = new_name

    save_config(cfg)
    return {"status": "ok", "new_name": new_name}


@router.post("/api/providers/fetch-models")
async def fetch_provider_models(req: FetchModelsRequest):
    """Fetch available models from a provider's /v1/models endpoint with metadata hints."""
    base_url = req.base_url.strip()
    if not base_url:
        return {"ok": False, "message": "Base URL 不能为空"}

    provider_name = (req.provider_name or "").strip() or None
    api_key = _resolve_api_key(req.api_key)
    if not api_key and provider_name:
        cfg = load_config()
        if provider_name in cfg.providers:
            api_key = cfg.providers[provider_name].api_key

    try:
        status_code, payload = await _fetch_provider_models(provider_name, base_url, api_key)
    except httpx.TimeoutException:
        return {"ok": False, "message": "连接超时，请检查网络、代理或 Base URL"}
    except httpx.RequestError as exc:
        return {"ok": False, "message": f"连接失败: {exc.__class__.__name__}"}

    if status_code >= 400:
        return {
            "ok": False,
            "message": (f"API Key 无效或没有访问权限" if status_code in {401, 403}
                        else f"Provider 返回 HTTP {status_code}"),
            "status_code": status_code,
        }

    model_ids = _extract_model_ids(payload)
    models = [_suggest_model_metadata(mid) for mid in model_ids]
    return {
        "ok": True,
        "message": f"获取到 {len(models)} 个模型",
        "models": models,
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
        litellm_provider=req.litellm_provider,
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


@router.put("/api/web-search/settings")
def update_web_search_settings(req: WebSearchSettingsRequest):
    cfg = load_config()
    cfg.web_search = _apply_web_search_update(cfg.web_search, req)
    save_config(cfg)
    return {"status": "ok", "web_search": _web_search_settings_payload(cfg)}


@router.post("/api/web-search/test")
async def test_web_search(req: WebSearchTestRequest):
    try:
        cfg = load_config()
        web = _apply_web_search_update(cfg.web_search, req)
        override = web.model_dump()
        results, provider = await perform_web_search(
            req.query,
            max_results=3,
            config_override=override,
        )
    except Exception as exc:
        return {"ok": False, "message": f"Web search failed: {exc}"}
    return {
        "ok": True,
        "message": f"Search succeeded via {provider}",
        "provider": provider,
        "result_count": len(results),
        "results": [r.to_dict() for r in results],
    }


@router.post("/api/config/reload")
def force_config_reload():
    """强制刷新后端配置缓存"""
    cfg = reload_config()
    return {"status": "ok", "default_model": cfg.settings.default_model}


@router.post("/api/roles/reload")
def reload_roles():
    """强制重新加载内置角色定义（code-expert 等）"""
    RoleManager.reload()
    return {"status": "ok"}


@router.post("/api/skills/reload")
def reload_skills():
    """强制重新加载 Superpowers skills（MATCH_RULES + SKILL.md）"""
    SkillManager.reload_skills()
    return {"status": "ok"}
