import os
import yaml
from typing import Dict, List, Optional
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

class Settings(BaseModel):
    default_model: str
    default_provider: str
    max_iterations: int = 50
    auto_approve: bool = False
    screenshot_on_step: bool = True
    sandbox_mode: str = "sandbox"

class AppConfig(BaseModel):
    providers: Dict[str, ProviderConfig]
    settings: Settings
    rag: RagConfig = RagConfig()

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
            "models": [m.model_dump() for m in provider.models],
        }

    data: Dict[str, object] = {
        "providers": providers_data,
        "settings": cfg.settings.model_dump(),
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
