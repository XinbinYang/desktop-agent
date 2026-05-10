from app.tools.base import BaseTool, ToolResult
from app.mcp.manager import get_mcp_manager


class McpToolProxy(BaseTool):
    """MCP 工具代理：运行时动态生成的工具，包装外部 MCP Server 的工具。"""

    def __init__(self, server_id: str, tool_name: str, description: str, parameters: dict):
        self.name = f"mcp_{server_id}_{tool_name}"
        self.description = description
        self.parameters = parameters
        self._server_id = server_id
        self._tool_name = tool_name

    async def execute(self, **kwargs) -> ToolResult:
        manager = get_mcp_manager()
        result = await manager.call_tool(self._server_id, self._tool_name, kwargs)
        return ToolResult(output=result.get("content", ""), error=result.get("error", ""))
