import sys
import pytest
from unittest.mock import patch, AsyncMock
from app.tools.shell_tool import ShellExecuteTool, ShellStartTool


class TestShellExecuteTool:
    @pytest.fixture
    def tool(self):
        return ShellExecuteTool()

    @pytest.mark.asyncio
    async def test_simple_echo(self, tool):
        if sys.platform == "win32":
            result = await tool.execute(command="echo hello")
        else:
            result = await tool.execute(command="echo hello")
        assert result.error == ""
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_dangerous_command_blocked(self, tool):
        result = await tool.execute(command="rm -rf /")
        assert "不可逆操作" in result.error
        assert "用户确认" in result.error

    @pytest.mark.asyncio
    async def test_git_push_force_blocked(self, tool):
        result = await tool.execute(command="git push --force origin main")
        assert "不可逆操作" in result.error

    @pytest.mark.asyncio
    async def test_git_push_f_blocked(self, tool):
        result = await tool.execute(command="git push -f origin main")
        assert "不可逆操作" in result.error

    @pytest.mark.asyncio
    async def test_git_reset_hard_blocked(self, tool):
        result = await tool.execute(command="git reset --hard HEAD~1")
        assert "不可逆操作" in result.error

    @pytest.mark.asyncio
    async def test_git_clean_fd_blocked(self, tool):
        result = await tool.execute(command="git clean -fd")
        assert "不可逆操作" in result.error

    @pytest.mark.asyncio
    async def test_git_branch_D_blocked(self, tool):
        result = await tool.execute(command="git branch -D feature-x")
        assert "不可逆操作" in result.error

    @pytest.mark.asyncio
    async def test_git_checkout_dot_blocked(self, tool):
        result = await tool.execute(command="git checkout .")
        assert "不可逆操作" in result.error

    @pytest.mark.asyncio
    async def test_normal_git_push_allowed(self, tool):
        """Normal git push (without --force) should not be blocked."""
        result = await tool.execute(command="git push origin main")
        assert "不可逆操作" not in result.error

    @pytest.mark.asyncio
    async def test_timeout(self, tool):
        if sys.platform == "win32":
            cmd = "ping -n 5 127.0.0.1"
        else:
            cmd = "sleep 3"
        result = await tool.execute(command=cmd, timeout=1)
        assert "超时" in result.error

    @pytest.mark.asyncio
    async def test_invalid_command(self, tool):
        result = await tool.execute(command="this_command_does_not_exist_12345")
        # Should return non-zero exit code
        assert result.error != "" or "无输出" in result.output


class TestShellStartTool:
    @pytest.fixture
    def tool(self):
        return ShellStartTool()

    @pytest.mark.asyncio
    async def test_start_process(self, tool):
        if sys.platform == "win32":
            result = await tool.execute(command="cmd /c echo hi")
        else:
            result = await tool.execute(command="echo hi")
        assert "PID" in result.output
        assert result.error == ""

    @pytest.mark.asyncio
    async def test_start_dangerous_command_blocked(self, tool):
        result = await tool.execute(command="rm -rf /")
        assert "不可逆操作" in result.error
        assert "用户确认" in result.error

    @pytest.mark.asyncio
    async def test_start_git_push_force_blocked(self, tool):
        result = await tool.execute(command="git push --force origin main")
        assert "不可逆操作" in result.error

    @pytest.mark.asyncio
    async def test_start_git_push_f_blocked(self, tool):
        result = await tool.execute(command="git push -f origin main")
        assert "不可逆操作" in result.error

    @pytest.mark.asyncio
    async def test_start_git_reset_hard_blocked(self, tool):
        result = await tool.execute(command="git reset --hard HEAD~1")
        assert "不可逆操作" in result.error

    @pytest.mark.asyncio
    async def test_start_git_clean_fd_blocked(self, tool):
        result = await tool.execute(command="git clean -fd")
        assert "不可逆操作" in result.error

    @pytest.mark.asyncio
    async def test_start_git_branch_D_blocked(self, tool):
        result = await tool.execute(command="git branch -D feature-x")
        assert "不可逆操作" in result.error

    @pytest.mark.asyncio
    async def test_start_safe_command_allowed(self, tool):
        if sys.platform == "win32":
            result = await tool.execute(command="cmd /c echo safe_test")
        else:
            result = await tool.execute(command="echo safe_test")
        assert result.error == ""
