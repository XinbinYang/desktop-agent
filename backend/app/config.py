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

class AutoApproveRule(BaseModel):
    """A permission rule for auto-approval of tool calls."""
    tool: str = ""             # Tool name pattern (supports * wildcard)
    path: str = ""             # File path pattern (supports * wildcard)
    action: str = "allow"      # "allow" or "deny"
    risk: str = ""             # Optional: only match specific risk level ("low", "medium", "high")

class Settings(BaseModel):
    default_model: str
    default_provider: str
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
    auto_delegate_coding: str = "suggest"
    review_gate_enabled: bool = True
    auto_approve_rules: List[AutoApproveRule] = []

class AppConfig(BaseModel):
    providers: Dict[str, ProviderConfig]
    settings: Settings
    rag: RagConfig = RagConfig()
    coding_agent: CodingAgentConfig = CodingAgentConfig()
    personal_agent: PersonalAgentConfig = PersonalAgentConfig()

_config: Optional[AppConfig] = None


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

    # Backward compat: ensure personal_agent key exists
    if "personal_agent" not in raw:
        raw["personal_agent"] = {}

    # 保存原始 api_key（env var 解析前），用于 save_config 时写回
    raw_api_keys: Dict[str, str] = {}
    for provider_name, provider in raw.get("providers", {}).items():
        raw_api_keys[provider_name] = provider.get("api_key", "")
        key = raw_api_keys[provider_name]
        if key.startswith("${") and key.endswith("}"):
            env_var = key[2:-1]
            provider["api_key"] = os.environ.get(env_var, "")

    _config = AppConfig(**raw)
    # Preserve the raw (un-expanded) api_key so save_config can round-trip env-var syntax.
    for provider_name, provider in _config.providers.items():
        if provider_name in raw_api_keys:
            provider._raw_api_key = raw_api_keys[provider_name]
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

    data: Dict[str, object] = {
        "providers": providers_data,
        "settings": cfg.settings.model_dump(),
        "rag": cfg.rag.model_dump(),
        "coding_agent": cfg.coding_agent.model_dump(),
        "personal_agent": cfg.personal_agent.model_dump(),
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

    Priority: agent-specific override -> global default_model.
    """
    cfg = load_config()
    default = cfg.settings.default_model
    if agent_type == "coding":
        override = cfg.coding_agent.model
    elif agent_type == "personal":
        override = cfg.personal_agent.model
    else:
        override = ""
    return override if override else default

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
