import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


from app.config import (
    mask_api_key, load_config, save_config, reload_config,
    AppConfig, ProviderConfig, Settings, ModelInfo,
    CONFIG_PATH,
)


class TestMaskApiKey:
    def test_env_var_key(self):
        assert mask_api_key("${OPENAI_API_KEY}") == "${OPENAI_API_KEY}"

    def test_env_var_key_nested(self):
        assert mask_api_key("${ANTHROPIC_AUTH_TOKEN}") == "${ANTHROPIC_AUTH_TOKEN}"

    def test_short_key(self):
        assert mask_api_key("abc") == "abc..."
        assert mask_api_key("12345678") == "123..."

    def test_long_key(self):
        result = mask_api_key("fake-kimi-M2fg26F8IQpjm2iRnTyRcKG7G4f3LoeMVlsO4vYm9lSgJp8CUVM5a3d8xLiRBwOW")
        assert result == "fak...BwOW"

    def test_empty_key(self):
        assert mask_api_key("") == ""


class TestSaveConfig:
    @pytest.fixture
    def tmp_config(self, tmp_path):
        """Create a copy of models.yaml in tmp_path and override CONFIG_PATH."""
        import app.config as cfg_mod
        original = cfg_mod.CONFIG_PATH
        tmp_yaml = tmp_path / "models.yaml"
        # Start fresh: write a minimal valid config
        yaml_content = """providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    models:
    - id: gpt-4o
      name: GPT-4o
      context: 128000
      vision: true
settings:
  default_model: gpt-4o
  default_provider: openai
  max_iterations: 50
  auto_approve: false
  screenshot_on_step: true
"""
        import yaml
        from copy import deepcopy
        self._yaml_content = yaml_content
        self._original_path = original
        tmp_yaml.write_text(yaml_content, encoding="utf-8")
        # Redirect CONFIG_PATH
        cfg_mod.CONFIG_PATH = tmp_yaml
        # Reset cache
        cfg_mod._config = None
        yield tmp_yaml
        cfg_mod.CONFIG_PATH = original
        cfg_mod._config = None

    def test_save_and_reload_roundtrip(self, tmp_config):
        cfg = load_config()
        assert cfg.settings.max_iterations == 50

        cfg.settings.max_iterations = 99
        save_config(cfg)

        # Reload and verify
        reloaded = reload_config()
        assert reloaded.settings.max_iterations == 99

    def test_save_preserves_env_var_syntax(self, tmp_config):
        cfg = load_config()
        # The raw key should be stored as _raw_api_key
        raw = getattr(cfg.providers["openai"], "_raw_api_key", None)
        assert raw == "${OPENAI_API_KEY}"

        # Save and check YAML content
        save_config(cfg)
        import yaml
        with open(tmp_config, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["providers"]["openai"]["api_key"] == "${OPENAI_API_KEY}"

    def test_save_preserves_plaintext_key(self, tmp_config):
        cfg = load_config()
        # Change to a plaintext key
        cfg.providers["openai"].api_key = "fake-plaintext-key"
        cfg.providers["openai"]._raw_api_key = "fake-plaintext-key"
        save_config(cfg)

        import yaml
        with open(tmp_config, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["providers"]["openai"]["api_key"] == "fake-plaintext-key"

    def test_provider_update_blank_api_key_keeps_existing_secret(self, tmp_config):
        from app.routes.settings import ProviderUpdateRequest, update_provider

        update_provider(
            "openai",
            ProviderUpdateRequest(
                base_url="https://api.openai.com/v1",
                api_key="",
                models=[{"id": "gpt-4o-mini", "name": "GPT-4o Mini", "context": 128000, "vision": True}],
            ),
        )

        import yaml
        with open(tmp_config, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["providers"]["openai"]["api_key"] == "${OPENAI_API_KEY}"
        assert data["providers"]["openai"]["models"][0]["id"] == "gpt-4o-mini"

    def test_cache_invalidated_after_save(self, tmp_config):
        import app.config as cfg_mod
        cfg = load_config()
        assert cfg_mod._config is not None
        save_config(cfg)
        assert cfg_mod._config is None

    def test_reload_invalidates_cache(self, tmp_config):
        import app.config as cfg_mod
        cfg1 = load_config()
        assert cfg_mod._config is not None
        cfg2 = reload_config()
        assert cfg1.settings.max_iterations == cfg2.settings.max_iterations

    def test_atomic_write(self, tmp_config, monkeypatch):
        cfg = load_config()
        original_content = tmp_config.read_text(encoding="utf-8")
        cfg.settings.max_iterations = 42

        # Simulate write failure during os.replace
        import builtins
        original_replace = os.replace
        called = [False]

        def fake_replace(src, dst, **kwargs):
            called[0] = True
            raise OSError("Simulated write failure")

        monkeypatch.setattr(os, "replace", fake_replace)

        with pytest.raises(OSError, match="Simulated write failure"):
            save_config(cfg)

        # Original file should be unchanged
        assert called[0]
        assert tmp_config.read_text(encoding="utf-8") == original_content
