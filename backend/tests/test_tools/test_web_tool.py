from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.tools.web_tool import (
    SearchResult,
    WebFetchTool,
    WebSearchTool,
    extract_html_text,
    filter_results,
    perform_web_search,
)


def _cfg(**overrides):
    defaults = {
        "provider": "auto",
        "brave_api_key": "",
        "tavily_api_key": "",
        "serpapi_api_key": "",
        "fallback_enabled": True,
        "allow_private_network": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(web_search=SimpleNamespace(**defaults))


@pytest.mark.asyncio
async def test_web_search_auto_uses_configured_brave(monkeypatch):
    import app.tools.web_tool as web_tool

    monkeypatch.setattr(web_tool, "load_config", lambda: _cfg(brave_api_key="brave-key"))
    brave = AsyncMock(return_value=[
        SearchResult(title="Docs", url="https://docs.example.com", snippet="Official docs", source="brave")
    ])
    duck = AsyncMock(return_value=[])
    monkeypatch.setattr(web_tool, "_search_brave", brave)
    monkeypatch.setattr(web_tool, "_search_duckduckgo", duck)

    results, provider = await perform_web_search("docs")

    assert provider == "brave"
    assert results[0].url == "https://docs.example.com"
    brave.assert_awaited_once()
    duck.assert_not_called()


@pytest.mark.asyncio
async def test_web_search_falls_back_to_duckduckgo(monkeypatch):
    import app.tools.web_tool as web_tool

    monkeypatch.setattr(web_tool, "load_config", lambda: _cfg())
    duck = AsyncMock(return_value=[
        SearchResult(title="Fallback", url="https://example.com", snippet="Result", source="duckduckgo")
    ])
    monkeypatch.setattr(web_tool, "_search_duckduckgo", duck)

    results, provider = await perform_web_search("fallback")

    assert provider == "duckduckgo"
    assert results[0].title == "Fallback"


def test_web_search_domain_filters_results():
    results = [
        SearchResult(title="A", url="https://docs.python.org/3/"),
        SearchResult(title="B", url="https://example.com/page"),
        SearchResult(title="C", url="https://blog.python.org/post"),
    ]

    filtered = filter_results(results, include_domains=["python.org"], exclude_domains=["blog.python.org"])

    assert [r.title for r in filtered] == ["A"]


def test_extract_html_text_removes_scripts():
    text, title = extract_html_text("""
        <html><head><title>Example</title><script>bad()</script></head>
        <body><h1>Hello</h1><p>Readable body</p></body></html>
    """)

    assert title == "Example"
    assert "Hello" in text
    assert "Readable body" in text
    assert "bad()" not in text


@pytest.mark.asyncio
async def test_web_fetch_blocks_private_urls(monkeypatch):
    import app.tools.web_tool as web_tool

    monkeypatch.setattr(web_tool, "load_config", lambda: _cfg(allow_private_network=False))

    result = await WebFetchTool().execute("http://192.168.1.10")

    assert "Private network URLs are blocked" in result.error


@pytest.mark.asyncio
async def test_web_search_tool_returns_metadata(monkeypatch):
    import app.tools.web_tool as web_tool

    async def fake_search(*args, **kwargs):
        return [SearchResult(title="One", url="https://example.com", snippet="Snippet", source="fake")], "fake"

    monkeypatch.setattr(web_tool, "perform_web_search", fake_search)

    result = await WebSearchTool().execute("anything")

    assert result.error == ""
    assert "https://example.com" in result.output
    assert result.metadata["web_search"]["provider"] == "fake"
