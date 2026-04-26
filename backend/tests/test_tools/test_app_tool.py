import sys
import pytest
from unittest.mock import patch, MagicMock
from app.tools.app_tool import (
    AppOpenTool, AppListWindowsTool, AppFindWindowTool,
    AppClickTool, AppTypeTool
)


class TestAppOpenTool:
    @pytest.fixture
    def tool(self):
        return AppOpenTool()

    @pytest.mark.asyncio
    async def test_open_program(self, tool):
        with patch("app.tools.app_tool.subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            result = await tool.execute(command="notepad")
            assert result.error == ""
            assert "12345" in result.output


@pytest.mark.skipif(sys.platform != "win32", reason="pywinauto is Windows-only")
class TestAppListWindowsTool:
    @pytest.fixture
    def tool(self):
        return AppListWindowsTool()

    @pytest.mark.asyncio
    async def test_list_windows_mocked(self, tool):
        mock_window = MagicMock()
        mock_window.window_text.return_value = "Test Window"

        mock_desktop = MagicMock()
        mock_desktop.windows.return_value = [mock_window]

        with patch("app.tools.app_tool.HAS_PYWINAUTO", True):
            with patch("app.tools.app_tool.Desktop", return_value=mock_desktop):
                result = await tool.execute()
                assert result.error == ""
                assert "Test Window" in result.output


@pytest.mark.skipif(sys.platform != "win32", reason="pywinauto is Windows-only")
class TestAppFindWindowTool:
    @pytest.fixture
    def tool(self):
        return AppFindWindowTool()

    @pytest.mark.asyncio
    async def test_find_window_mocked(self, tool):
        mock_window = MagicMock()
        mock_window.window_text.return_value = "Notepad - test.txt"
        mock_window.rectangle.return_value = MagicMock(left=0, top=0, right=100, bottom=100)
        mock_window.handle = 1234

        mock_desktop = MagicMock()
        mock_desktop.windows.return_value = [mock_window]

        with patch("app.tools.app_tool.HAS_PYWINAUTO", True):
            with patch("app.tools.app_tool.Desktop", return_value=mock_desktop):
                result = await tool.execute(title="Notepad")
                assert result.error == ""
                assert "Notepad" in result.output
