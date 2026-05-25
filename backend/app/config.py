import os
import yaml
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, PrivateAttr

from app.runtime_paths import default_config_path


CONFIG_PATH = default_config_path()

class ModelInfo(BaseModel):
    id: str
    name: str
    context: int
    vision: bool = False

class ProviderConfig(BaseModel):
    base_url: str
    api_key: str
    litellm_provider: str = ""
    models: List[ModelInfo]

    # The api_key field stores the resolved value (env vars expanded). The raw
    # form ("${OPENAI_API_KEY}" or a literal key) is preserved separately so
    # save_config can write it back without losing env-var indirection.
    _raw_api_key: str = PrivateAttr(default="")

class RagConfig(BaseModel):
    embedding_model: str = "all-MiniLM-L6-v2"
    chunk_size: int = 500
    chunk_overlap: int = 50
    min_score: float = 0.3
    top_k: int = 5

class PersonalAgentConfig(BaseModel):
    model: str = ""
    thinking_intensity: str = "medium"

class CodingAgentConfig(BaseModel):
    enabled: bool = True
    default_execution_mode: str = "worktree"
    max_fix_rounds: int = 2
    max_parallel_workers: int = 3
    require_verification: bool = True
    require_review: bool = True
    auto_generate_repo_map: bool = True
    model: str = ""
    thinking_intensity: str = "medium"

class WebSearchConfig(BaseModel):
    provider: str = "auto"
    brave_api_key: str = ""
    tavily_api_key: str = ""
    serpapi_api_key: str = ""
    fallback_enabled: bool = True
    allow_private_network: bool = False

    _raw_brave_api_key: str = PrivateAttr(default="")
    _raw_tavily_api_key: str = PrivateAttr(default="")
    _raw_serpapi_api_key: str = PrivateAttr(default="")

class AutoApproveRule(BaseModel):
    """A permission rule for auto-approval of tool calls."""
    tool: str = ""             # Tool name pattern (supports * wildcard)
    path: str = ""             # File path pattern (supports * wildcard)
    action: str = "allow"      # "allow" or "deny"
    risk: str = ""             # Optional: only match specific risk level ("low", "medium", "high")

class Settings(BaseModel):
    # Legacy fields kept for older runtime config files and clients. Runtime
    # model selection now comes from personal_agent/coding_agent settings.
    default_model: str = ""
    default_provider: str = ""
    max_iterations: int = 10000
    auto_approve: bool = False
    screenshot_on_step: bool = True
    sandbox_mode: str = "sandbox"
    thinking_intensity_default: str = "medium"
    thinking_policy_by_provider: Dict[str, Dict[str, Any]] = {}
    collaboration_mode: str = "serial"
    max_parallel_agents: int = 3
    collaboration_enabled: bool = True
    default_collaboration_mode: str = "hybrid"
    auto_delegate_coding: str = "off"
    review_gate_enabled: bool = True
    auto_approve_rules: List[AutoApproveRule] = []

class AppConfig(BaseModel):
    providers: Dict[str, ProviderConfig]
    settings: Settings
    rag: RagConfig = RagConfig()
    coding_agent: CodingAgentConfig = CodingAgentConfig()
    personal_agent: PersonalAgentConfig = PersonalAgentConfig()
    web_search: WebSearchConfig = WebSearchConfig()

_config: Optional[AppConfig] = None
_WEB_SEARCH_KEY_FIELDS: tuple[str, ...] = ("brave_api_key", "tavily_api_key", "serpapi_api_key")


def mask_api_key(key: str) -> str:
    """对 API Key 进行脱敏处理。保留 ${ENV_VAR} 语法原样，短 key 截断，长 key 只显示首尾。"""
    if not key:
        return ""
    if key.startswith("${") and key.endswith("}"):
        return key
    if len(key) <= 8:
        return key[:3] + "..."
    return key[:3] + "..." + key[-4:]


def load_config() -> AppConfig:
    global _config
    if _config is not None:
        return _config

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raw = {}

    # Backward compat: migrate old global default_model into explicit per-agent
    # defaults so runtime decisions no longer depend on global model fields.
    settings = raw.setdefault("settings", {})
    legacy_default_model = str(settings.get("default_model") or "")
    if "personal_agent" not in raw or not isinstance(raw.get("personal_agent"), dict):
        raw["personal_agent"] = {}
    if "coding_agent" not in raw or not isinstance(raw.get("coding_agent"), dict):
        raw["coding_agent"] = {}
    if legacy_default_model:
        if not str(raw["personal_agent"].get("model") or "").strip():
            raw["personal_agent"]["model"] = legacy_default_model
        if not str(raw["coding_agent"].get("model") or "").strip():
            raw["coding_agent"]["model"] = legacy_default_model
    if "web_search" not in raw:
        raw["web_search"] = {}

    # 保存原始 api_key（env var 解析前），用于 save_config 时写回
    raw_api_keys: Dict[str, str] = {}
    for provider_name, provider in raw.get("providers", {}).items():
        raw_api_keys[provider_name] = provider.get("api_key", "")
        key = raw_api_keys[provider_name]
        if key.startswith("${") and key.endswith("}"):
            env_var = key[2:-1]
            provider["api_key"] = os.environ.get(env_var, "")

    raw_web_keys: Dict[str, str] = {}
    web_search = raw.get("web_search", {}) or {}
    for field in _WEB_SEARCH_KEY_FIELDS:
        raw_web_keys[field] = web_search.get(field, "")
        key = raw_web_keys[field]
        if isinstance(key, str) and key.startswith("${") and key.endswith("}"):
            web_search[field] = os.environ.get(key[2:-1], "")
    raw["web_search"] = web_search

    _config = AppConfig(**raw)
    # Preserve the raw (un-expanded) api_key so save_config can round-trip env-var syntax.
    for provider_name, provider in _config.providers.items():
        if provider_name in raw_api_keys:
            provider._raw_api_key = raw_api_keys[provider_name]
    for field in _WEB_SEARCH_KEY_FIELDS:
        setattr(_config.web_search, f"_raw_{field}", raw_web_keys.get(field, ""))
    return _config


def save_config(cfg: AppConfig) -> None:
    """将 AppConfig 写回 models.yaml。使用原子写入防止文件损坏，保留 ${ENV_VAR} 语法。"""
    providers_data: Dict[str, dict] = {}
    for name, provider in cfg.providers.items():
        raw_key = provider._raw_api_key or provider.api_key
        providers_data[name] = {
            "base_url": provider.base_url,
            "api_key": raw_key,
            "litellm_provider": provider.litellm_provider,
            "models": [m.model_dump() for m in provider.models],
        }

    web_search_data = cfg.web_search.model_dump()
    for field in _WEB_SEARCH_KEY_FIELDS:
        raw_key = getattr(cfg.web_search, f"_raw_{field}", "") or getattr(cfg.web_search, field)
        web_search_data[field] = raw_key

    data: Dict[str, object] = {
        "providers": providers_data,
        "settings": cfg.settings.model_dump(),
        "rag": cfg.rag.model_dump(),
        "coding_agent": cfg.coding_agent.model_dump(),
        "personal_agent": cfg.personal_agent.model_dump(),
        "web_search": web_search_data,
    }

    # 原子写入：先写临时文件，再 os.replace
    import os as _os
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = CONFIG_PATH.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    _os.replace(tmp_path, CONFIG_PATH)

    global _config
    _config = None


def reload_config() -> AppConfig:
    """强制重新加载配置（使缓存失效并重新读取 YAML）。"""
    global _config
    _config = None
    return load_config()

def get_provider_for_model(model_id: str) -> Optional[tuple[str, ProviderConfig]]:
    cfg = load_config()
    for name, provider in cfg.providers.items():
        for m in provider.models:
            if m.id == model_id:
                return name, provider
    return None

def model_supports_vision(model_id: str) -> bool:
    """Return True only if the given model id is configured as vision-capable."""
    if not model_id:
        return False
    cfg = load_config()
    for provider in cfg.providers.values():
        for m in provider.models:
            if m.id == model_id:
                return bool(m.vision)
    return False


def list_all_models() -> List[dict]:
    cfg = load_config()
    result = []
    for provider_name, provider in cfg.providers.items():
        for m in provider.models:
            result.append({
                "id": m.id,
                "name": m.name,
                "provider": provider_name,
                "vision": m.vision,
                "context": m.context
            })
    return result

def get_model_for_agent(agent_type: str) -> str:
    """Resolve the effective model ID for a given agent type.

    Runtime model selection is agent-scoped. Old global default_model values
    are migrated into agent configs in load_config().
    """
    cfg = load_config()
    if agent_type == "coding":
        return (cfg.coding_agent.model or "").strip()
    if agent_type == "personal":
        return (cfg.personal_agent.model or "").strip()
    return ""

def get_thinking_intensity_for_agent(agent_type: str) -> str:
    """Resolve the effective thinking intensity for a given agent type."""
    cfg = load_config()
    default = cfg.settings.thinking_intensity_default or "medium"
    if agent_type == "coding":
        override = cfg.coding_agent.thinking_intensity
    elif agent_type == "personal":
        override = cfg.personal_agent.thinking_intensity
    else:
        override = ""
    result = override if override else default
    if result not in ("low", "medium", "high"):
        result = "medium"
    return result
