import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.agent import AgentSession
from app.tools.mcp_tool import McpToolProxy


class TestAgentSessionDynamicTools:
    @pytest.fixture
    def session(self):
        return AgentSession(model_id="gpt-4o", session_id="test-dynamic")

    def test_dynamic_registry_initially_empty(self, session):
        assert session.dynamic_registry.list_names() == []
        schemas = session.dynamic_registry.get_schemas()
        assert schemas == []

    def test_get_tool_schemas_includes_dynamic(self, session):
        from app.tools import get_tool_schemas
        static_count = len(get_tool_schemas())

        # 注册一个动态工具
        proxy = McpToolProxy("srv1", "greet", "Say hello", {"type": "object", "properties": {}})
        session.dynamic_registry.register(proxy)

        combined = get_tool_schemas(session.dynamic_registry)
        assert len(combined) == static_count + 1
        assert any(s["function"]["name"] == "mcp_srv1_greet" for s in combined)

    def test_get_tool_with_dynamic_registry(self, session):
        from app.tools import get_tool
        proxy = McpToolProxy("srv1", "calc", "Calculate", {"type": "object", "properties": {}})
        session.dynamic_registry.register(proxy)

        # 应该能从 dynamic_registry 获取
        tool = get_tool("mcp_srv1_calc", session.dynamic_registry)
        assert tool.name == "mcp_srv1_calc"
        assert tool.description == "Calculate"

    def test_get_tool_fallback_to_static(self, session):
        from app.tools import get_tool
        # 不传递 dynamic_registry 时应该获取静态工具
        tool = get_tool("screenshot")
        assert tool.name == "screenshot"

    def test_list_tool_names_includes_dynamic(self, session):
        from app.tools import list_tool_names
        static_names = list_tool_names()

        proxy = McpToolProxy("srv1", "tool1", "desc", {"type": "object", "properties": {}})
        session.dynamic_registry.register(proxy)

        combined = list_tool_names(session.dynamic_registry)
        assert len(combined) == len(static_names) + 1
        assert "mcp_srv1_tool1" in combined

    def test_refresh_mcp_tools(self, session):
        mock_server = MagicMock()
        mock_server.id = "test-srv"
        mock_server.connected = True
        tool_a = MagicMock()
        tool_a.name = "tool_a"
        tool_a.description = "Tool A"
        tool_a.parameters = {"type": "object"}
        tool_b = MagicMock()
        tool_b.name = "tool_b"
        tool_b.description = "Tool B"
        tool_b.parameters = {"type": "object"}
        mock_server.tools = [tool_a, tool_b]

        with patch("app.mcp.manager.get_mcp_manager") as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.list_servers.return_value = [mock_server]
            mock_get_manager.return_value = mock_manager

            session.refresh_mcp_tools()

            assert len(session.dynamic_registry.list_names()) == 2
            assert "mcp_test-srv_tool_a" in session.dynamic_registry.list_names()
            assert "mcp_test-srv_tool_b" in session.dynamic_registry.list_names()

            # 验证 system prompt 被刷新
            assert session.messages[0]["role"] == "system"

    def test_refresh_mcp_tools_clears_old(self, session):
        # 先注册一个旧工具
        old_proxy = McpToolProxy("old", "tool", "desc", {})
        session.dynamic_registry.register(old_proxy)
        assert "mcp_old_tool" in session.dynamic_registry.list_names()

        mock_server = MagicMock()
        mock_server.id = "new-srv"
        mock_server.connected = True
        new_tool = MagicMock()
        new_tool.name = "new_tool"
        new_tool.description = "New"
        new_tool.parameters = {}
        mock_server.tools = [new_tool]

        with patch("app.mcp.manager.get_mcp_manager") as mock_get_manager:
            mock_manager = MagicMock()
            mock_manager.list_servers.return_value = [mock_server]
            mock_get_manager.return_value = mock_manager

            session.refresh_mcp_tools()

            assert "mcp_old_tool" not in session.dynamic_registry.list_names()
            assert "mcp_new-srv_new_tool" in session.dynamic_registry.list_names()

    @pytest.mark.asyncio
    async def test_dynamic_tool_execution(self, session):
        proxy = McpToolProxy("srv", "echo", "Echo", {"type": "object", "properties": {"msg": {"type": "string"}}})
        session.dynamic_registry.register(proxy)

        with patch("app.tools.mcp_tool.get_mcp_manager") as mock_get_manager:
            class FakeManager:
                async def call_tool(self, server_id, tool_name, kwargs):
                    return {"content": "hello", "error": ""}
            mock_get_manager.return_value = FakeManager()

            result = await proxy.execute(msg="hello")
            assert result.output == "hello"
            assert result.error == ""
