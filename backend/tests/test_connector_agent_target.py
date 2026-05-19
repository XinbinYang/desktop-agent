from pathlib import Path

from app.connectors.base import ConnectorConfig
from app.connectors.discord_connector import DiscordConnector
from app.connectors.feishu_connector import FeishuConnector


def _write_agent_model_config(path: Path) -> None:
    path.write_text(
        """
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key: test-key
    models:
    - id: personal-model
      name: Personal Model
      context: 128000
      vision: true
    - id: coding-model
      name: Coding Model
      context: 128000
      vision: false
settings:
  default_model: legacy-model
  default_provider: openai
personal_agent:
  model: personal-model
coding_agent:
  model: coding-model
""",
        encoding="utf-8",
    )


def test_legacy_global_default_migrates_to_agent_models(tmp_path, monkeypatch):
    import app.config as cfg_mod

    config_yaml = tmp_path / "models.yaml"
    config_yaml.write_text(
        """
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key: test-key
    models:
    - id: legacy-model
      name: Legacy Model
      context: 128000
settings:
  default_model: legacy-model
  default_provider: openai
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", config_yaml)
    cfg_mod._config = None

    cfg = cfg_mod.load_config()

    assert cfg.personal_agent.model == "legacy-model"
    assert cfg.coding_agent.model == "legacy-model"
    assert cfg_mod.get_model_for_agent("personal") == "legacy-model"
    assert cfg_mod.get_model_for_agent("coding") == "legacy-model"


def test_connector_defaults_to_personal_agent(tmp_path, monkeypatch):
    import app.config as cfg_mod

    config_yaml = tmp_path / "models.yaml"
    _write_agent_model_config(config_yaml)
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", config_yaml)
    cfg_mod._config = None

    connector = DiscordConnector(
        ConnectorConfig(name="discord", display_name="Discord", config={})
    )

    assert connector.target_agent == "personal"
    assert connector.get_session_id("user", "channel") == "discord:personal:user:channel"
    assert connector.resolve_agent_target() == ("personal", "desktop-agent", "personal-model")


def test_connector_can_target_coding_agent(tmp_path, monkeypatch):
    import app.config as cfg_mod

    config_yaml = tmp_path / "models.yaml"
    _write_agent_model_config(config_yaml)
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", config_yaml)
    cfg_mod._config = None

    connector = DiscordConnector(
        ConnectorConfig(name="discord", display_name="Discord", config={"target_agent": "coding"})
    )

    assert connector.target_agent == "coding"
    assert connector.get_session_id("user", "channel") == "discord:coding:user:channel"
    assert connector.resolve_agent_target() == ("coding", "code-expert", "coding-model")


def test_feishu_connector_can_target_coding_agent(tmp_path, monkeypatch):
    import app.config as cfg_mod

    config_yaml = tmp_path / "models.yaml"
    _write_agent_model_config(config_yaml)
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", config_yaml)
    cfg_mod._config = None

    connector = FeishuConnector(
        ConnectorConfig(name="feishu", display_name="Feishu", config={"target_agent": "coding"})
    )

    assert connector.target_agent == "coding"
    assert connector.get_session_id("user", "chat") == "feishu:coding:user:chat"
    assert connector.resolve_agent_target() == ("coding", "code-expert", "coding-model")


def test_connector_update_rejects_invalid_target_agent(client):
    from app.connectors import get_connector_manager

    manager = get_connector_manager()
    manager.register(DiscordConnector())

    response = client.put(
        "/api/connectors/discord",
        json={"config": {"bot_token": "token", "target_agent": "worker"}},
    )

    assert response.status_code == 422
    assert "target_agent" in response.json()["detail"]
