from __future__ import annotations

import html
import ipaddress
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, async_playwright

from app.config import load_config
from app.tools.base import BaseTool, ToolResult


SEARCH_TIMEOUT = 15
FETCH_TIMEOUT = 20
MAX_FETCH_BYTES = 3_000_000
MIN_RENDERED_TEXT_CHARS = 500
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "DesktopAgent/1.0 Safari/537.36"
)

SEARCH_PROVIDERS = {"auto", "brave", "tavily", "serpapi", "duckduckgo"}
KEY_FIELDS = {"brave": "brave_api_key", "tavily": "tavily_api_key", "serpapi": "serpapi_api_key"}


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
        }


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "svg", "noscript"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag in {"br", "p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "svg", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        self.parts.append(text)
        self.parts.append(" ")

    @property
    def title(self) -> str:
        return normalize_text(" ".join(self.title_parts))

    @property
    def text(self) -> str:
        return normalize_text("".join(self.parts))


def resolve_secret(value: str) -> str:
    value = (value or "").strip()
    if value.startswith("${") and value.endswith("}"):
        import os

        return os.environ.get(value[2:-1], "")
    return value


def normalize_text(text: str) -> str:
    text = html.unescape(text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    compact: list[str] = []
    blank_seen = False
    for line in lines:
        if not line:
            if compact and not blank_seen:
                compact.append("")
            blank_seen = True
            continue
        compact.append(line)
        blank_seen = False
    return "\n".join(compact).strip()


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style|svg|noscript)\b.*?</\1>", " ", text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return normalize_text(text)


def extract_html_text(content: str) -> tuple[str, str]:
    parser = _TextExtractor()
    parser.feed(content or "")
    parser.close()
    return parser.text, parser.title


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0:
        max_chars = 12000
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip() + "\n\n[truncated]", True


def decode_duckduckgo_url(url: str) -> str:
    parsed = urlparse(html.unescape(url))
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    if url.startswith("//"):
        return "https:" + url
    return html.unescape(url)


def host_is_localhost(host: str) -> bool:
    host = (host or "").strip("[]").lower()
    return host in {"localhost", "127.0.0.1", "::1"} or host.startswith("127.")


def host_is_blocked_private(host: str) -> bool:
    host = (host or "").strip("[]")
    if host_is_localhost(host):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host.lower().endswith(".local")
    return ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved


def validate_fetch_url(url: str, *, allow_private_network: bool = False) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http and https URLs are allowed")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError("URL must include a host")
    if not allow_private_network and host_is_blocked_private(parsed.hostname):
        raise ValueError("Private network URLs are blocked by Web Fetch settings")
    return parsed.geturl()


def domain_matches(url: str, domains: list[str]) -> bool:
    if not domains:
        return True
    host = (urlparse(url).hostname or "").lower()
    for domain in domains:
        d = domain.lower().strip()
        if d and (host == d or host.endswith("." + d)):
            return True
    return False


def filter_results(
    results: list[SearchResult],
    *,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    max_results: int = 5,
) -> list[SearchResult]:
    filtered: list[SearchResult] = []
    seen: set[str] = set()
    include_domains = include_domains or []
    exclude_domains = exclude_domains or []
    for result in results:
        if not result.url or result.url in seen:
            continue
        if include_domains and not domain_matches(result.url, include_domains):
            continue
        if exclude_domains and domain_matches(result.url, exclude_domains):
            continue
        seen.add(result.url)
        filtered.append(result)
        if len(filtered) >= max_results:
            break
    return filtered


def search_provider_order(config_override: dict[str, Any] | None = None) -> list[str]:
    cfg = load_config().web_search
    override = config_override or {}
    provider = str(override.get("provider") or cfg.provider or "auto").lower()
    if provider not in SEARCH_PROVIDERS:
        provider = "auto"
    fallback_enabled = bool(override.get("fallback_enabled", cfg.fallback_enabled))
    keys = {
        "brave": resolve_secret(str(override.get("brave_api_key") or cfg.brave_api_key or "")),
        "tavily": resolve_secret(str(override.get("tavily_api_key") or cfg.tavily_api_key or "")),
        "serpapi": resolve_secret(str(override.get("serpapi_api_key") or cfg.serpapi_api_key or "")),
    }
    if provider == "auto":
        order = [name for name in ("brave", "tavily", "serpapi") if keys[name]]
        if fallback_enabled:
            order.append("duckduckgo")
        return order
    return [provider]


def provider_key(provider: str, config_override: dict[str, Any] | None = None) -> str:
    cfg = load_config().web_search
    override = config_override or {}
    field = KEY_FIELDS.get(provider)
    if not field:
        return ""
    return resolve_secret(str(override.get(field) or getattr(cfg, field, "") or ""))


async def _search_brave(query: str, max_results: int, key: str) -> list[SearchResult]:
    if not key:
        raise RuntimeError("Brave Search API key is not configured")
    async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        response = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max(1, min(max_results, 20))},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
        )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("web", {}).get("results", []) if isinstance(payload, dict) else []
    return [
        SearchResult(
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            snippet=strip_html(str(item.get("description") or "")),
            source="brave",
        )
        for item in items
        if isinstance(item, dict)
    ]


async def _search_tavily(
    query: str,
    max_results: int,
    key: str,
    include_domains: list[str] | None,
    exclude_domains: list[str] | None,
) -> list[SearchResult]:
    if not key:
        raise RuntimeError("Tavily API key is not configured")
    body: dict[str, Any] = {
        "api_key": key,
        "query": query,
        "max_results": max(1, min(max_results, 20)),
        "search_depth": "basic",
    }
    if include_domains:
        body["include_domains"] = include_domains
    if exclude_domains:
        body["exclude_domains"] = exclude_domains
    async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        response = await client.post("https://api.tavily.com/search", json=body)
    response.raise_for_status()
    payload = response.json()
    items = payload.get("results", []) if isinstance(payload, dict) else []
    return [
        SearchResult(
            title=str(item.get("title") or ""),
            url=str(item.get("url") or ""),
            snippet=strip_html(str(item.get("content") or "")),
            source="tavily",
        )
        for item in items
        if isinstance(item, dict)
    ]


async def _search_serpapi(query: str, max_results: int, key: str) -> list[SearchResult]:
    if not key:
        raise RuntimeError("SerpAPI key is not configured")
    async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        response = await client.get(
            "https://serpapi.com/search.json",
            params={"engine": "google", "q": query, "api_key": key, "num": max(1, min(max_results, 20))},
        )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("organic_results", []) if isinstance(payload, dict) else []
    return [
        SearchResult(
            title=str(item.get("title") or ""),
            url=str(item.get("link") or ""),
            snippet=strip_html(str(item.get("snippet") or "")),
            source="serpapi",
        )
        for item in items
        if isinstance(item, dict)
    ]


async def _search_duckduckgo(query: str, max_results: int) -> list[SearchResult]:
    async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        response = await client.get("https://lite.duckduckgo.com/lite/", params={"q": query})
    response.raise_for_status()
    text = response.text
    pattern = re.compile(
        r'<a[^>]+href="(?P<href>[^"]+)"[^>]*class="[^"]*result-link[^"]*"[^>]*>(?P<title>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        pattern = re.compile(
            r'<a[^>]+class="[^"]*result-link[^"]*"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        matches = list(pattern.finditer(text))

    snippets = [
        strip_html(m.group(1))
        for m in re.finditer(
            r'<td[^>]+class="[^"]*result-snippet[^"]*"[^>]*>(.*?)</td>',
            text,
            re.IGNORECASE | re.DOTALL,
        )
    ]
    results: list[SearchResult] = []
    for idx, match in enumerate(matches[:max_results]):
        results.append(
            SearchResult(
                title=strip_html(match.group("title")),
                url=decode_duckduckgo_url(match.group("href")),
                snippet=snippets[idx] if idx < len(snippets) else "",
                source="duckduckgo",
            )
        )
    return results


async def perform_web_search(
    query: str,
    *,
    max_results: int = 5,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    config_override: dict[str, Any] | None = None,
) -> tuple[list[SearchResult], str]:
    query = (query or "").strip()
    if not query:
        raise ValueError("query is required")
    max_results = max(1, min(int(max_results or 5), 20))
    errors: list[str] = []
    for provider in search_provider_order(config_override):
        try:
            if provider == "brave":
                results = await _search_brave(query, max_results, provider_key("brave", config_override))
            elif provider == "tavily":
                results = await _search_tavily(
                    query,
                    max_results,
                    provider_key("tavily", config_override),
                    include_domains,
                    exclude_domains,
                )
            elif provider == "serpapi":
                results = await _search_serpapi(query, max_results, provider_key("serpapi", config_override))
            elif provider == "duckduckgo":
                results = await _search_duckduckgo(query, max_results)
            else:
                continue
            filtered = filter_results(
                results,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
                max_results=max_results,
            )
            if filtered:
                return filtered, provider
            errors.append(f"{provider}: no results")
        except Exception as exc:
            errors.append(f"{provider}: {exc.__class__.__name__}: {exc}")
    if not errors:
        raise RuntimeError("No search provider is available")
    raise RuntimeError("; ".join(errors))


def format_search_results(results: list[SearchResult], provider: str) -> str:
    lines = [f"Search provider: {provider}", ""]
    for idx, result in enumerate(results, 1):
        lines.append(f"{idx}. {result.title or result.url}")
        lines.append(f"URL: {result.url}")
        if result.snippet:
            lines.append(f"Snippet: {result.snippet}")
        lines.append("")
    return "\n".join(lines).strip()


def looks_like_spa(html_text: str, extracted_text: str) -> bool:
    if len(extracted_text) >= MIN_RENDERED_TEXT_CHARS:
        return False
    lowered = html_text.lower()
    return (
        "<script" in lowered
        and (
            'id="root"' in lowered
            or "id='root'" in lowered
            or 'id="app"' in lowered
            or "id='app'" in lowered
            or "__next_data__" in lowered
            or "vite" in lowered
        )
    )


async def fetch_http_text(url: str) -> tuple[str, str, int, str, str]:
    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT,
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain,text/markdown,application/json,*/*;q=0.8",
        },
    ) as client:
        response = await client.get(url)
    response.raise_for_status()
    content = response.content[:MAX_FETCH_BYTES]
    content_type = response.headers.get("content-type", "")
    encoding = response.encoding or "utf-8"
    text = content.decode(encoding, errors="replace")
    final_url = str(response.url)
    if "application/json" in content_type:
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except ValueError:
            pass
        return normalize_text(text), "", response.status_code, final_url, content_type
    if "html" in content_type or "<html" in text[:500].lower():
        body, title = extract_html_text(text)
        return body, title, response.status_code, final_url, content_type
    return normalize_text(text), "", response.status_code, final_url, content_type


async def fetch_browser_text(url: str) -> tuple[str, str, str]:
    playwright = None
    browser = None
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        await page.goto(url, wait_until="networkidle", timeout=30000)
        title = await page.title()
        text = await page.evaluate("() => document.body ? document.body.innerText : ''")
        return normalize_text(str(text or "")), title, page.url
    finally:
        if browser is not None:
            await browser.close()
        if playwright is not None:
            await playwright.stop()


async def perform_web_fetch(url: str, *, max_chars: int = 12000, render_mode: str = "auto") -> dict[str, Any]:
    cfg = load_config().web_search
    validated_url = validate_fetch_url(url, allow_private_network=cfg.allow_private_network)
    mode = (render_mode or "auto").lower()
    if mode not in {"auto", "http", "browser"}:
        raise ValueError("render_mode must be auto, http, or browser")

    if mode == "browser":
        text, title, final_url = await fetch_browser_text(validated_url)
        status_code = 200
        source = "browser"
        content_type = "rendered"
    else:
        text, title, status_code, final_url, content_type = await fetch_http_text(validated_url)
        source = "http"
        if mode == "auto":
            try:
                async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
                    raw = await client.get(validated_url)
                raw_text = raw.text
            except Exception:
                raw_text = ""
            if raw_text and looks_like_spa(raw_text, text):
                text, rendered_title, rendered_url = await fetch_browser_text(validated_url)
                title = rendered_title or title
                final_url = rendered_url or final_url
                source = "browser"
                content_type = "rendered"

    text, truncated = truncate_text(text, max_chars)
    return {
        "url": final_url,
        "title": title,
        "status_code": status_code,
        "content_type": content_type,
        "source": source,
        "text": text,
        "truncated": truncated,
    }


def format_fetch_result(data: dict[str, Any]) -> str:
    title = data.get("title") or data.get("url") or "Web page"
    lines = [
        f"# {title}",
        f"URL: {data.get('url', '')}",
        f"Status: {data.get('status_code', '')}",
        f"Source: {data.get('source', '')}",
        "",
        str(data.get("text") or ""),
    ]
    return "\n".join(lines).strip()


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web for current information and return concise results with titles, URLs, and snippets."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return, 1-20",
                "default": 5,
            },
            "include_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional domain allowlist, e.g. ['docs.python.org']",
                "default": [],
            },
            "exclude_domains": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional domain blocklist",
                "default": [],
            },
        },
        "required": ["query"],
    }

    async def execute(
        self,
        query: str,
        max_results: int = 5,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> ToolResult:
        try:
            results, provider = await perform_web_search(
                query,
                max_results=max_results,
                include_domains=include_domains or [],
                exclude_domains=exclude_domains or [],
            )
            return ToolResult(
                output=format_search_results(results, provider),
                metadata={"web_search": {"provider": provider, "results": [r.to_dict() for r in results]}},
            )
        except httpx.TimeoutException:
            return ToolResult(error="Web search timed out")
        except httpx.HTTPStatusError as exc:
            return ToolResult(error=f"Web search failed: HTTP {exc.response.status_code}")
        except Exception as exc:
            return ToolResult(error=f"Web search failed: {exc}")


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetch a URL and return readable page text. Use browser rendering for JavaScript-heavy pages when needed."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch"},
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return",
                "default": 12000,
            },
            "render_mode": {
                "type": "string",
                "enum": ["auto", "http", "browser"],
                "description": "Fetch strategy. auto tries HTTP first and renders JS pages when needed.",
                "default": "auto",
            },
        },
        "required": ["url"],
    }

    async def execute(self, url: str, max_chars: int = 12000, render_mode: str = "auto") -> ToolResult:
        try:
            data = await perform_web_fetch(url, max_chars=max_chars, render_mode=render_mode)
            return ToolResult(output=format_fetch_result(data), metadata={"web_fetch": data})
        except ValueError as exc:
            return ToolResult(error=str(exc))
        except PlaywrightTimeoutError:
            return ToolResult(error="Web fetch browser rendering timed out")
        except PlaywrightError as exc:
            return ToolResult(error=f"Web fetch browser rendering failed: {exc}")
        except httpx.TimeoutException:
            return ToolResult(error="Web fetch timed out")
        except httpx.HTTPStatusError as exc:
            return ToolResult(error=f"Web fetch failed: HTTP {exc.response.status_code}")
        except Exception as exc:
            return ToolResult(error=f"Web fetch failed: {exc}")
