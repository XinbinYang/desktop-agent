import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from app.mcp.models import McpServerConfig, McpToolInfo
from app.mcp.client import MCPClientWrapper
from app.mcp.manager import McpManager


class TestMCPClientWrapper:
    @pytest.fixture
    def stdio_config(self):
        return McpServerConfig(
            id="test-stdio",
            transport="stdio",
            command="echo",
            args=["hello"],
        )

    @pytest.fixture
    def sse_config(self):
        return McpServerConfig(
            id="test-sse",
            transport="sse",
            url="http://localhost:3001/sse",
        )

    @staticmethod
    def _make_session_mock(tools=None):
        """Build an AsyncMock that behaves as an async context manager (returns self on __aenter__)."""
        session = AsyncMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.initialize = AsyncMock()
        session.list_tools = AsyncMock(return_value=MagicMock(tools=tools or []))
        return session

    @staticmethod
    def _make_transport_context():
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    @pytest.mark.asyncio
    async def test_connect_stdio_success(self, stdio_config, monkeypatch, tmp_path):
        monkeypatch.setattr("app.mcp.client.StdioServerParameters", MagicMock)

        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test tool"
        mock_tool.inputSchema = {"type": "object", "properties": {}}
        mock_session = self._make_session_mock(tools=[mock_tool])
        mock_context = self._make_transport_context()

        with patch("app.mcp.client.stdio_client", return_value=mock_context):
            with patch("app.mcp.client.ClientSession", return_value=mock_session):
                client = MCPClientWrapper(stdio_config)
                result = await client.connect()
                assert result is True
                assert client.is_connected()
                assert len(client.tools) == 1
                assert client.tools[0].name == "test_tool"

    @pytest.mark.asyncio
    async def test_connect_stdio_failure(self, stdio_config):
        with patch("app.mcp.client.stdio_client", side_effect=Exception("Command not found")):
            client = MCPClientWrapper(stdio_config)
            result = await client.connect()
            assert result is False
            assert not client.is_connected()
            assert "Command not found" in client.error

    @pytest.mark.asyncio
    async def test_disconnect(self, stdio_config):
        mock_context = self._make_transport_context()
        mock_session = self._make_session_mock()

        with patch("app.mcp.client.stdio_client", return_value=mock_context):
            with patch("app.mcp.client.ClientSession", return_value=mock_session):
                client = MCPClientWrapper(stdio_config)
                await client.connect()
                assert client.is_connected()
                await client.disconnect()
                assert not client.is_connected()
                # Both contexts must be exited on disconnect.
                mock_session.__aexit__.assert_awaited()
                mock_context.__aexit__.assert_awaited()

    @pytest.mark.asyncio
    async def test_disconnect_after_failed_connect_does_not_raise(self, stdio_config):
        """Connect failure must not leave a half-open stack that crashes disconnect."""
        mock_context = self._make_transport_context()
        mock_session = self._make_session_mock()
        mock_session.initialize = AsyncMock(side_effect=RuntimeError("init failed"))

        with patch("app.mcp.client.stdio_client", return_value=mock_context):
            with patch("app.mcp.client.ClientSession", return_value=mock_session):
                client = MCPClientWrapper(stdio_config)
                ok = await client.connect()
                assert ok is False
                assert "init failed" in (client.error or "")
                # Stack already cleaned up; calling disconnect again is a no-op.
                await client.disconnect()
                assert not client.is_connected()

    @pytest.mark.asyncio
    async def test_call_tool(self, stdio_config):
        mock_context = self._make_transport_context()
        mock_result = MagicMock()
        mock_result.content = [MagicMock(text="result text")]
        mock_session = self._make_session_mock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        with patch("app.mcp.client.stdio_client", return_value=mock_context):
            with patch("app.mcp.client.ClientSession", return_value=mock_session):
                client = MCPClientWrapper(stdio_config)
                await client.connect()
                result = await client.call_tool("test_tool", {"arg": "value"})
                assert result["content"] == "result text"
                assert result["error"] == ""

    @pytest.mark.asyncio
    async def test_call_tool_not_connected(self, stdio_config):
        client = MCPClientWrapper(stdio_config)
        result = await client.call_tool("test_tool", {})
        assert "未连接" in result["error"]

    @pytest.mark.asyncio
    async def test_call_tool_error(self, stdio_config):
        mock_context = self._make_transport_context()
        mock_session = self._make_session_mock()
        mock_session.call_tool = AsyncMock(side_effect=Exception("Tool error"))

        with patch("app.mcp.client.stdio_client", return_value=mock_context):
            with patch("app.mcp.client.ClientSession", return_value=mock_session):
                client = MCPClientWrapper(stdio_config)
                await client.connect()
                result = await client.call_tool("test_tool", {})
                assert "Tool error" in result["error"]


class TestMcpManager:
    @pytest.fixture(autouse=True)
    def isolate_config(self, monkeypatch, tmp_path):
        test_config = tmp_path / "mcp.yaml"
        monkeypatch.setattr("app.mcp.manager.MCP_CONFIG_PATH", test_config)
        import app.mcp.manager as manager_mod
        manager_mod._mcp_manager = None
        yield
        manager_mod._mcp_manager = None

    def test_load_empty_config(self):
        manager = McpManager()
        assert manager.list_servers() == []

    def test_load_config(self, tmp_path, monkeypatch):
        import yaml
        config_path = tmp_path / "mcp.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump({
                "servers": {
                    "fs": {
                        "transport": "stdio",
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem"],
                    }
                }
            }, f)
        monkeypatch.setattr("app.mcp.manager.MCP_CONFIG_PATH", config_path)
        import app.mcp.manager as manager_mod
        manager_mod._mcp_manager = None
        manager = McpManager()
        servers = manager.list_servers()
        assert len(servers) == 1
        assert servers[0].id == "fs"
        assert servers[0].config.transport == "stdio"

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self, tmp_path, monkeypatch):
        import yaml
        config_path = tmp_path / "mcp.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump({
                "servers": {
                    "test": {
                        "transport": "stdio",
                        "command": "echo",
                        "args": [],
                    }
                }
            }, f)
        monkeypatch.setattr("app.mcp.manager.MCP_CONFIG_PATH", config_path)
        import app.mcp.manager as manager_mod
        manager_mod._mcp_manager = None
        manager = McpManager()

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.disconnect = AsyncMock()
        mock_client.is_connected = MagicMock(return_value=True)
        mock_client.tools = [McpToolInfo(name="tool1", description="desc", parameters={})]
        mock_client.error = None

        with patch("app.mcp.manager.MCPClientWrapper", return_value=mock_client):
            success = await manager.connect("test")
            assert success is True
            server = manager.get_server("test")
            assert server.connected is True
            assert len(server.tools) == 1

            await manager.disconnect("test")
            assert "test" not in manager._clients

    @pytest.mark.asyncio
    async def test_connect_nonexistent_server(self):
        manager = McpManager()
        success = await manager.connect("nonexistent")
        assert success is False

    @pytest.mark.asyncio
    async def test_call_tool(self, tmp_path, monkeypatch):
        import yaml
        config_path = tmp_path / "mcp.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump({
                "servers": {
                    "test": {
                        "transport": "stdio",
                        "command": "echo",
                        "args": [],
                    }
                }
            }, f)
        monkeypatch.setattr("app.mcp.manager.MCP_CONFIG_PATH", config_path)
        import app.mcp.manager as manager_mod
        manager_mod._mcp_manager = None
        manager = McpManager()

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock(return_value=True)
        mock_client.is_connected = MagicMock(return_value=True)
        mock_client.tools = []
        mock_client.call_tool = AsyncMock(return_value={"content": "hello", "error": ""})

        with patch("app.mcp.manager.MCPClientWrapper", return_value=mock_client):
            await manager.connect("test")
            result = await manager.call_tool("test", "greet", {"name": "world"})
            assert result["content"] == "hello"
            mock_client.call_tool.assert_awaited_once_with("greet", {"name": "world"})

    @pytest.mark.asyncio
    async def test_call_tool_not_connected(self):
        manager = McpManager()
        result = await manager.call_tool("test", "greet", {})
        assert "未连接" in result["error"]

    def test_get_all_tools(self, tmp_path, monkeypatch):
        import yaml
        config_path = tmp_path / "mcp.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump({
                "servers": {
                    "srv1": {"transport": "stdio", "command": "echo", "args": []},
                    "srv2": {"transport": "stdio", "command": "echo", "args": []},
                }
            }, f)
        monkeypatch.setattr("app.mcp.manager.MCP_CONFIG_PATH", config_path)
        import app.mcp.manager as manager_mod
        manager_mod._mcp_manager = None
        manager = McpManager()

        mock_client1 = MagicMock()
        mock_client1.is_connected.return_value = True
        mock_client1.tools = [McpToolInfo(name="tool1", description="d1", parameters={})]

        mock_client2 = MagicMock()
        mock_client2.is_connected.return_value = True
        mock_client2.tools = [McpToolInfo(name="tool2", description="d2", parameters={})]

        manager._clients["srv1"] = mock_client1
        manager._clients["srv2"] = mock_client2

        all_tools = manager.get_all_tools()
        assert len(all_tools) == 2
        assert all_tools[0].name == "mcp_srv1_tool1"
        assert all_tools[1].name == "mcp_srv2_tool2"
