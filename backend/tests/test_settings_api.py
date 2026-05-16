import pytest


class TestSettingsAPI:
    @pytest.fixture(autouse=True)
    def isolate_config_file(self, tmp_path, monkeypatch):
        import app.config as cfg_mod

        config_yaml = tmp_path / "models.yaml"
        config_yaml.write_text(
            """
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_key: ${OPENAI_API_KEY}
    models:
    - id: gpt-4o
      name: GPT-4o
      context: 128000
      vision: true
  kimi:
    base_url: https://api.kimi.com/coding/v1
    api_key: ${KIMI_API_KEY}
    models:
    - id: kimi-for-coding
      name: Kimi
      context: 256000
      vision: true
settings:
  default_model: kimi-for-coding
  default_provider: kimi
  max_iterations: 50
  auto_approve: false
  screenshot_on_step: true
""",
            encoding="utf-8",
        )
        monkeypatch.setattr(cfg_mod, "CONFIG_PATH", config_yaml)
        cfg_mod._config = None
        yield
        cfg_mod._config = None

    def test_get_settings(self, client):
        """GET /api/settings returns providers with masked keys + settings."""
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert "providers" in data
        assert "settings" in data
        assert "openai" in data["providers"]
        # API key should be masked
        openai = data["providers"]["openai"]
        assert "api_key_masked" in openai
        assert "api_key_configured" in openai
        assert openai["api_key_configured"] is False
        assert openai["api_key_masked"] == "${OPENAI_API_KEY}" or "..." in openai["api_key_masked"]
        # Settings should have expected keys
        settings = data["settings"]
        assert "default_model" in settings
        assert "default_provider" in settings
        assert "max_iterations" in settings

    def test_put_settings_updates(self, client):
        """PUT /api/settings partially updates global settings."""
        response = client.put("/api/settings", json={"max_iterations": 25})
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Verify the update persisted
        response = client.get("/api/settings")
        assert response.json()["settings"]["max_iterations"] == 25

        # Restore
        client.put("/api/settings", json={"max_iterations": 50})

    def test_put_provider_updates_config(self, client):
        """PUT /api/providers/{name} updates a provider."""
        # First get current state
        get_resp = client.get("/api/settings")
        orig_models = get_resp.json()["providers"]["openai"]["models"]

        # Update with modified models
        new_models = orig_models + [{"id": "test-model", "name": "Test", "context": 8000, "vision": False}]
        response = client.put("/api/providers/openai", json={
            "base_url": "https://api.openai.com/v1",
            "api_key": "fake-test123",
            "models": new_models,
        })
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Verify
        get_resp2 = client.get("/api/settings")
        updated_models = get_resp2.json()["providers"]["openai"]["models"]
        assert len(updated_models) == len(new_models)
        assert any(m["id"] == "test-model" for m in updated_models)

        # Restore original (remove test model)
        client.put("/api/providers/openai", json={
            "base_url": "https://api.openai.com/v1",
            "api_key": "${OPENAI_API_KEY}",
            "models": orig_models,
        })

    def test_post_provider_creates_new(self, client):
        """POST /api/providers creates a new provider."""
        response = client.post("/api/providers", json={
            "name": "test_provider",
            "base_url": "https://test.api.com/v1",
            "api_key": "test-key-123",
            "models": [{"id": "test-model", "name": "Test Model", "context": 32000, "vision": False}],
        })
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Verify it exists
        get_resp = client.get("/api/settings")
        assert "test_provider" in get_resp.json()["providers"]

        # Cleanup
        client.delete("/api/providers/test_provider")

    def test_post_duplicate_provider_rejected(self, client):
        """POST /api/providers with existing name returns 409."""
        response = client.post("/api/providers", json={
            "name": "openai",
            "base_url": "https://test.com/v1",
            "api_key": "test",
            "models": [],
        })
        assert response.status_code == 409

    def test_delete_provider(self, client):
        """DELETE /api/providers/{name} removes a provider."""
        # Create a temp provider first
        client.post("/api/providers", json={
            "name": "to_delete",
            "base_url": "https://tmp.com/v1",
            "api_key": "tmp",
            "models": [],
        })

        response = client.delete("/api/providers/to_delete")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

        # Verify gone
        get_resp = client.get("/api/settings")
        assert "to_delete" not in get_resp.json()["providers"]

    def test_delete_default_provider_rejected(self, client):
        """Cannot delete the default provider."""
        response = client.delete("/api/providers/kimi")
        assert response.status_code == 400

    def test_delete_nonexistent_provider(self, client):
        """DELETE nonexistent returns 404."""
        response = client.delete("/api/providers/nonexistent_xyz")
        assert response.status_code == 404

    def test_config_reload(self, client):
        """POST /api/config/reload returns default model."""
        response = client.post("/api/config/reload")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert "default_model" in response.json()

    def test_provider_connection_test_success(self, client, monkeypatch):
        """POST /api/providers/test validates model listing without exposing keys."""
        async def fake_fetch(provider_name, base_url, api_key):
            assert provider_name == "openai"
            assert base_url == "https://api.openai.com/v1"
            assert api_key == "fake-key"
            return 200, {"data": [{"id": "gpt-4o"}]}

        monkeypatch.setattr("app.routes.settings._fetch_provider_models", fake_fetch)

        response = client.post("/api/providers/test", json={
            "provider_name": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "fake-key",
            "model_id": "gpt-4o",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["model_found"] is True
        assert "fake-key" not in str(data)

    def test_provider_connection_test_blank_key_uses_existing_env_key(self, client, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "fake-env-key")

        async def fake_fetch(provider_name, base_url, api_key):
            assert api_key == "fake-env-key"
            return 200, {"data": [{"id": "gpt-4o"}]}

        monkeypatch.setattr("app.routes.settings._fetch_provider_models", fake_fetch)

        response = client.post("/api/providers/test", json={
            "provider_name": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "model_id": "gpt-4o",
        })
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_provider_connection_test_missing_key_rejected_before_network(self, client, monkeypatch):
        async def fake_fetch(provider_name, base_url, api_key):
            raise AssertionError("network should not be called")

        monkeypatch.setattr("app.routes.settings._fetch_provider_models", fake_fetch)

        response = client.post("/api/providers/test", json={
            "provider_name": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "model_id": "gpt-4o",
        })
        data = response.json()
        assert response.status_code == 200
        assert data["ok"] is False
        assert "API Key" in data["message"]

    def test_provider_connection_test_model_not_found(self, client, monkeypatch):
        async def fake_fetch(provider_name, base_url, api_key):
            return 200, {"data": [{"id": "other-model"}]}

        monkeypatch.setattr("app.routes.settings._fetch_provider_models", fake_fetch)

        response = client.post("/api/providers/test", json={
            "provider_name": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "fake-key",
            "model_id": "gpt-4o",
        })
        data = response.json()
        assert response.status_code == 200
        assert data["ok"] is False
        assert data["model_found"] is False

    def test_roles_reload(self, client):
        """POST /api/roles/reload should clear cache and return ok."""
        response = client.post("/api/roles/reload")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        # Verify roles still work after reload
        roles_resp = client.get("/api/roles")
        assert roles_resp.status_code == 200
        assert len(roles_resp.json()["roles"]) >= 4

    def test_skills_reload(self, client):
        """POST /api/skills/reload should clear cache and return ok."""
        response = client.post("/api/skills/reload")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        # Verify skills still work after reload
        skills_resp = client.get("/api/skills")
        assert skills_resp.status_code == 200
        assert len(skills_resp.json()["skills"]) > 0
