from pathlib import Path
import asyncio

from app.connectors.base import ConnectorConfig, PlatformConnector
from app.connectors.discord_connector import DiscordConnector
from app.connectors.feishu_connector import FeishuConnector


class NotifyTestConnector(PlatformConnector):
    name = "notify_test"
    display_name = "Notify Test"
    description = "Test connector"

    def __init__(self):
        super().__init__(ConnectorConfig(name=self.name, display_name=self.display_name))
        self.sent_messages = []

    @property
    def status(self) -> str:
        return "running"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send_notification(self, message: str):
        self.sent_messages.append(message)
        return {"message_id": "msg-1"}


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
    assert connector.tool_visibility == "silent"
    assert connector.get_session_id("user", "channel") == "discord_personal_user_channel"
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
    assert connector.get_session_id("user", "channel") == "discord_coding_user_channel"
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
    assert connector.get_session_id("user", "chat") == "feishu_coding_user_chat"
    assert connector.resolve_agent_target() == ("coding", "code-expert", "coding-model")


def test_social_connectors_expose_tool_visibility_schema():
    discord_schema = DiscordConnector().get_config_schema()["properties"]["tool_visibility"]
    feishu_schema = FeishuConnector().get_config_schema()["properties"]["tool_visibility"]

    for schema in (discord_schema, feishu_schema):
        assert schema["default"] == "silent"
        assert schema["enum"] == ["silent", "debug"]


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


def test_connector_update_rejects_invalid_tool_visibility(client):
    from app.connectors import get_connector_manager

    manager = get_connector_manager()
    manager.register(DiscordConnector())

    response = client.put(
        "/api/connectors/discord",
        json={"config": {"bot_token": "token", "tool_visibility": "verbose"}},
    )

    assert response.status_code == 422
    assert "tool_visibility" in response.json()["detail"]


def test_connector_test_message_endpoint_sends(client):
    from app.connectors import get_connector_manager

    manager = get_connector_manager()
    connector = NotifyTestConnector()
    manager.register(connector)

    response = client.post(
        "/api/connectors/notify_test/test-message",
        json={"message": "ping"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    assert response.json()["details"] == {"message_id": "msg-1"}
    assert connector.sent_messages == ["ping"]


def test_connector_update_preserves_empty_sensitive_fields_and_masks_response(client):
    from app.connectors import get_connector_manager

    manager = get_connector_manager()
    manager.register(DiscordConnector())
    manager.update_config(
        "discord",
        {
            "bot_token": "discord-secret-token-1234",
            "target_agent": "personal",
            "notification_channel_id": "123",
        },
    )

    response = client.put(
        "/api/connectors/discord",
        json={
            "config": {
                "bot_token": "",
                "target_agent": "coding",
                "tool_visibility": "debug",
                "notification_channel_id": "456",
            }
        },
    )

    assert response.status_code == 200
    stored = manager.get("discord").config.config
    assert stored["bot_token"] == "discord-secret-token-1234"
    assert stored["target_agent"] == "coding"
    assert stored["tool_visibility"] == "debug"
    assert stored["notification_channel_id"] == "456"

    payload = client.get("/api/connectors/discord").json()
    assert payload["config"]["bot_token"]["configured"] is True
    assert "discord-secret-token-1234" not in str(payload)


async def test_feishu_callback_schedules_message_handler_on_main_loop(monkeypatch):
    connector = FeishuConnector(ConnectorConfig(name="feishu", display_name="Feishu"))
    seen = []

    async def fake_handle(event):
        seen.append(event)

    connector._loop = asyncio.get_running_loop()
    monkeypatch.setattr(connector, "_handle_feishu_message", fake_handle)

    event = object()
    connector._on_message_receive(event)
    await asyncio.sleep(0.05)

    assert seen == [event]
