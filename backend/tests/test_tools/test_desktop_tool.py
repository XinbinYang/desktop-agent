import pytest
from unittest.mock import patch, MagicMock
from app.tools.desktop_tool import (
    ScreenshotTool, MouseClickTool, MouseMoveTool,
    TypeTextTool, PressKeyTool, ScrollTool, GetScreenSizeTool
)


class TestScreenshotTool:
    @pytest.fixture
    def tool(self):
        return ScreenshotTool()

    @pytest.mark.asyncio
    async def test_screenshot_mocked(self, tool):
        mock_img = MagicMock()
        mock_img.size = (1920, 1080)
        mock_img.convert.return_value = mock_img
        mock_img.thumbnail.return_value = None

        with patch("app.tools.desktop_tool.pyautogui.screenshot", return_value=mock_img):
            with patch("app.tools.desktop_tool.HAS_PYAUTOGUI", True):
                result = await tool.execute()
                assert result.error == ""
                assert result.base64_image is not None


class TestMouseClickTool:
    @pytest.fixture
    def tool(self):
        return MouseClickTool()

    @pytest.mark.asyncio
    async def test_click_mocked(self, tool):
        with patch("app.tools.desktop_tool.pyautogui.click") as mock_click:
            with patch("app.tools.desktop_tool.HAS_PYAUTOGUI", True):
                result = await tool.execute(x=100, y=200, button="left", clicks=2)
                assert result.error == ""
                mock_click.assert_called_once_with(100, 200, clicks=2, button="left")


class TestGetScreenSizeTool:
    @pytest.fixture
    def tool(self):
        return GetScreenSizeTool()

    @pytest.mark.asyncio
    async def test_screen_size_mocked(self, tool):
        with patch("app.tools.desktop_tool.pyautogui.size", return_value=(1920, 1080)):
            with patch("app.tools.desktop_tool.HAS_PYAUTOGUI", True):
                result = await tool.execute()
                assert result.error == ""
                assert "1920x1080" in result.output
