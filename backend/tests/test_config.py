from app.config import load_config, get_provider_for_model, list_all_models, default_config_path


class TestLoadConfig:
    def test_default_config_path_uses_pyinstaller_meipass(self, monkeypatch, tmp_path):
        """Packaged PyInstaller builds should load bundled config from sys._MEIPASS."""
        from app import runtime_paths

        monkeypatch.setattr(runtime_paths.sys, "frozen", True, raising=False)
        monkeypatch.setattr(runtime_paths.sys, "_MEIPASS", str(tmp_path), raising=False)

        assert default_config_path() == tmp_path / "config" / "models.yaml"

    def test_user_config_copies_from_bundled_template(self, monkeypatch, tmp_path):
        """Customer runs seed a writable user config from the bundled template."""
        from app import runtime_paths

        bundle_root = tmp_path / "bundle"
        template = bundle_root / "config" / "models.yaml"
        template.parent.mkdir(parents=True)
        template.write_text(
            """
providers:
  p:
    base_url: http://x
    api_key: ${TEST_KEY}
    models:
      - id: m
        name: M
        context: 1
settings:
  default_model: m
  default_provider: p
""",
            encoding="utf-8",
        )
        user_data = tmp_path / "user-data"

        monkeypatch.setenv(runtime_paths.USER_DATA_ENV, str(user_data))
        monkeypatch.setattr(runtime_paths.sys, "frozen", True, raising=False)
        monkeypatch.setattr(runtime_paths.sys, "_MEIPASS", str(bundle_root), raising=False)

        path = runtime_paths.default_config_path()
        assert path == user_data / "backend" / "config" / "models.yaml"
        assert path.read_text(encoding="utf-8") == template.read_text(encoding="utf-8")

    def test_existing_user_config_takes_priority(self, monkeypatch, tmp_path):
        """Existing customer config is not overwritten by the bundled template."""
        from app import runtime_paths

        bundle_root = tmp_path / "bundle"
        template = bundle_root / "config" / "models.yaml"
        template.parent.mkdir(parents=True)
        template.write_text("settings:\n  default_model: bundled\n", encoding="utf-8")

        user_data = tmp_path / "user-data"
        existing = user_data / "backend" / "config" / "models.yaml"
        existing.parent.mkdir(parents=True)
        existing.write_text("settings:\n  default_model: customer\n", encoding="utf-8")

        monkeypatch.setenv(runtime_paths.USER_DATA_ENV, str(user_data))
        monkeypatch.setattr(runtime_paths.sys, "frozen", True, raising=False)
        monkeypatch.setattr(runtime_paths.sys, "_MEIPASS", str(bundle_root), raising=False)

        assert runtime_paths.default_config_path() == existing
        assert existing.read_text(encoding="utf-8") == "settings:\n  default_model: customer\n"

    def test_load_config_reads_yaml(self, monkeypatch, tmp_path):
        """Config loads from YAML and parses providers correctly"""
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  test_provider:
    base_url: http://localhost:8000
    api_key: test-key
    models:
      - id: test-model
        name: Test Model
        context: 4096
        vision: false
settings:
  default_model: test-model
  default_provider: test_provider
  max_iterations: 10
  auto_approve: false
  screenshot_on_step: false
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        # Reset cache
        from app import config
        config._config = None

        cfg = load_config()
        assert cfg.settings.default_model == "test-model"
        assert cfg.settings.max_iterations == 10
        assert "test_provider" in cfg.providers
        assert cfg.providers["test_provider"].api_key == "test-key"

    def test_env_var_substitution(self, monkeypatch, tmp_path):
        """API key with ${ENV_VAR} syntax is substituted from environment"""
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key: ${TEST_API_KEY}
    models:
      - id: gpt-4
        name: GPT-4
        context: 128000
settings:
  default_model: gpt-4
  default_provider: openai
""")
        monkeypatch.setenv("TEST_API_KEY", "fake-secret-123")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None

        cfg = load_config()
        assert cfg.providers["openai"].api_key == "fake-secret-123"

    def test_config_caching(self, monkeypatch, tmp_path):
        """Config is cached after first load"""
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  p:
    base_url: http://x
    api_key: k
    models:
      - id: m
        name: M
        context: 1
settings:
  default_model: m
  default_provider: p
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None

        cfg1 = load_config()
        cfg2 = load_config()
        assert cfg1 is cfg2


class TestGetProviderForModel:
    def test_returns_provider_for_existing_model(self, monkeypatch, tmp_path):
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  anthropic:
    base_url: https://api.anthropic.com
    api_key: key
    models:
      - id: claude-3
        name: Claude
        context: 200000
settings:
  default_model: claude-3
  default_provider: anthropic
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None

        result = get_provider_for_model("claude-3")
        assert result is not None
        assert result[0] == "anthropic"

    def test_returns_none_for_unknown_model(self, monkeypatch, tmp_path):
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  p:
    base_url: http://x
    api_key: k
    models:
      - id: m
        name: M
        context: 1
settings:
  default_model: m
  default_provider: p
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None

        assert get_provider_for_model("nonexistent") is None


class TestListAllModels:
    def test_lists_all_models(self, monkeypatch, tmp_path):
        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text("""
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key: k
    models:
      - id: gpt-4
        name: GPT-4
        context: 128000
        vision: true
  local:
    base_url: http://localhost:11434/v1
    api_key: ollama
    models:
      - id: llama3
        name: Llama 3
        context: 32000
settings:
  default_model: gpt-4
  default_provider: openai
""")
        monkeypatch.setattr("app.config.CONFIG_PATH", config_yaml)
        from app import config
        config._config = None

        models = list_all_models()
        assert len(models) == 2
        ids = [m["id"] for m in models]
        assert "gpt-4" in ids
        assert "llama3" in ids
