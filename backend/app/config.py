import os
import yaml
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "models.yaml"

class ModelInfo(BaseModel):
    id: str
    name: str
    context: int
    vision: bool = False

class ProviderConfig(BaseModel):
    base_url: str
    api_key: str
    models: List[ModelInfo]

class Settings(BaseModel):
    default_model: str
    default_provider: str
    max_iterations: int = 50
    auto_approve: bool = False
    screenshot_on_step: bool = True

class AppConfig(BaseModel):
    providers: Dict[str, ProviderConfig]
    settings: Settings

_config: Optional[AppConfig] = None

def load_config() -> AppConfig:
    global _config
    if _config is not None:
        return _config
    
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    
    # 解析环境变量
    for provider_name, provider in raw.get("providers", {}).items():
        key = provider.get("api_key", "")
        if key.startswith("${") and key.endswith("}"):
            env_var = key[2:-1]
            provider["api_key"] = os.environ.get(env_var, "")
    
    _config = AppConfig(**raw)
    return _config

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