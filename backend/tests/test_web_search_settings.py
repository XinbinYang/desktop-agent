import yaml


def test_settings_returns_web_search_config(client):
    response = client.get("/api/settings")

    assert response.status_code == 200
    data = response.json()
    assert data["web_search"]["provider"] in {"auto", "brave", "tavily", "serpapi", "duckduckgo"}
    assert "brave" in data["web_search"]["providers"]
    assert "api_key_masked" in data["web_search"]["providers"]["brave"]


def test_update_web_search_settings_saves_masked_key(client):
    response = client.put("/api/web-search/settings", json={
        "provider": "brave",
        "brave_api_key": "brave-secret-123456",
        "fallback_enabled": False,
    })

    assert response.status_code == 200
    payload = response.json()["web_search"]
    assert payload["provider"] == "brave"
    assert payload["fallback_enabled"] is False
    assert payload["providers"]["brave"]["api_key_configured"] is True
    assert payload["providers"]["brave"]["api_key_masked"] == "bra...3456"

    from app import config

    data = yaml.safe_load(config.CONFIG_PATH.read_text(encoding="utf-8"))
    assert data["web_search"]["brave_api_key"] == "brave-secret-123456"


def test_update_web_search_settings_blank_key_keeps_existing(client):
    client.put("/api/web-search/settings", json={
        "provider": "brave",
        "brave_api_key": "brave-secret-keep",
    })
    response = client.put("/api/web-search/settings", json={
        "provider": "auto",
        "brave_api_key": "",
    })

    assert response.status_code == 200
    from app import config

    data = yaml.safe_load(config.CONFIG_PATH.read_text(encoding="utf-8"))
    assert data["web_search"]["brave_api_key"] == "brave-secret-keep"


def test_update_web_search_rejects_unknown_provider(client):
    response = client.put("/api/web-search/settings", json={"provider": "unknown"})

    assert response.status_code == 400


def test_web_search_test_endpoint_uses_search_tool(client, monkeypatch):
    from app.tools.web_tool import SearchResult
    import app.routes.settings as settings_routes

    async def fake_search(*args, **kwargs):
        return [SearchResult(title="Docs", url="https://example.com", snippet="ok", source="fake")], "fake"

    monkeypatch.setattr(settings_routes, "perform_web_search", fake_search)

    response = client.post("/api/web-search/test", json={
        "provider": "duckduckgo",
        "query": "docs",
    })

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["provider"] == "fake"
    assert data["result_count"] == 1
