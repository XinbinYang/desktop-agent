import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.tools.browser_tool import (
    BrowserNavigateTool, BrowserClickTool, BrowserTypeTool,
    BrowserScreenshotTool, BrowserEvaluateTool, BrowserCloseTool
)


@pytest.fixture(autouse=True)
def reset_browser_state():
    """Reset global browser state before each test"""
    import app.tools.browser_tool as bt
    bt._playwright = None
    bt._browser = None
    bt._page = None
    yield
    bt._playwright = None
    bt._browser = None
    bt._page = None


class TestBrowserNavigateTool:
    @pytest.fixture
    def tool(self):
        return BrowserNavigateTool()

    @pytest.mark.asyncio
    async def test_navigate(self, tool):
        mock_page = MagicMock()
        mock_page.goto = AsyncMock()
        mock_page.title = AsyncMock(return_value="Test Page")

        with patch("app.tools.browser_tool._ensure_browser", new_callable=AsyncMock, return_value=mock_page):
            result = await tool.execute(url="https://example.com")
            assert result.error == ""
            assert "Test Page" in result.output


class TestBrowserClickTool:
    @pytest.fixture
    def tool(self):
        return BrowserClickTool()

    @pytest.mark.asyncio
    async def test_click_by_selector(self, tool):
        mock_page = MagicMock()
        mock_page.click = AsyncMock()

        with patch("app.tools.browser_tool._ensure_browser", new_callable=AsyncMock, return_value=mock_page):
            result = await tool.execute(selector="#submit")
            assert result.error == ""
            mock_page.click.assert_called_once_with("#submit", timeout=10000)


class TestBrowserTypeTool:
    @pytest.fixture
    def tool(self):
        return BrowserTypeTool()

    @pytest.mark.asyncio
    async def test_type_and_submit(self, tool):
        mock_page = MagicMock()
        mock_page.fill = AsyncMock()
        mock_page.press = AsyncMock()

        with patch("app.tools.browser_tool._ensure_browser", new_callable=AsyncMock, return_value=mock_page):
            result = await tool.execute(selector="#search", text="hello", submit=True)
            assert result.error == ""
            mock_page.fill.assert_called_once_with("#search", "hello", timeout=10000)
            mock_page.press.assert_called_once_with("#search", "Enter")


class TestBrowserScreenshotTool:
    @pytest.fixture
    def tool(self):
        return BrowserScreenshotTool()

    @pytest.mark.asyncio
    async def test_screenshot(self, tool):
        mock_page = MagicMock()
        mock_page.screenshot = AsyncMock(return_value=b"png_bytes")

        with patch("app.tools.browser_tool._ensure_browser", new_callable=AsyncMock, return_value=mock_page):
            result = await tool.execute()
            assert result.error == ""
            assert result.base64_image is not None


class TestBrowserEvaluateTool:
    @pytest.fixture
    def tool(self):
        return BrowserEvaluateTool()

    @pytest.mark.asyncio
    async def test_evaluate(self, tool):
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=42)

        with patch("app.tools.browser_tool._ensure_browser", new_callable=AsyncMock, return_value=mock_page):
            result = await tool.execute(script="1 + 41")
            assert result.error == ""
            assert "42" in result.output


class TestBrowserCloseTool:
    @pytest.fixture
    def tool(self):
        return BrowserCloseTool()

    @pytest.mark.asyncio
    async def test_close(self, tool):
        mock_page = MagicMock()
        mock_page.close = AsyncMock()
        mock_browser = MagicMock()
        mock_browser.close = AsyncMock()

        import app.tools.browser_tool as bt
        bt._SESSIONS['default'] = {
            "playwright": None,
            "browser": mock_browser,
            "page": mock_page,
        }

        result = await tool.execute()
        assert result.error == ""
        mock_page.close.assert_called_once()
        mock_browser.close.assert_called_once()
