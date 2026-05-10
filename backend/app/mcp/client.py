import asyncio
import os
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

from app.mcp.models import McpServerConfig, McpToolInfo

_MCP_TOOL_TIMEOUT = int(os.environ.get("DESKTOP_AGENT_MCP_TOOL_TIMEOUT", "60"))


class MCPClientWrapper:
    """MCP 客户端包装器：管理单个 MCP Server 的连接和工具调用。"""

    def __init__(self, config: McpServerConfig):
        self.config = config
        self.session: Optional[ClientSession] = None
        self._stack: Optional[AsyncExitStack] = None
        self.tools: List[McpToolInfo] = []
        self.error: Optional[str] = None

    async def connect(self) -> bool:
        """建立与 MCP Server 的连接。

        Uses AsyncExitStack so the transport stream and ClientSession are torn
        down in reverse order (session first, transport last) regardless of
        whether connect succeeds or raises mid-way. The previous manual
        __aexit__ pair leaked file descriptors when initialization failed.
        """
        stack = AsyncExitStack()
        try:
            if self.config.transport == "stdio":
                params = StdioServerParameters(
                    command=self.config.command or "",
                    args=self.config.args or [],
                    env=self.config.env,
                )
                read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
            elif self.config.transport == "sse":
                read_stream, write_stream = await stack.enter_async_context(
                    sse_client(self.config.url or "")
                )
            else:
                await stack.aclose()
                self.error = f"不支持的传输类型: {self.config.transport}"
                return False

            self.session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
            await self.session.initialize()

            tools_result = await self.session.list_tools()
            self.tools = [
                McpToolInfo(
                    name=t.name,
                    description=t.description or "",
                    parameters=t.inputSchema or {"type": "object", "properties": {}},
                )
                for t in (tools_result.tools or [])
            ]
            self._stack = stack
            self.error = None
            return True
        except Exception as e:
            self.error = str(e)
            try:
                await stack.aclose()
            except Exception:
                pass
            self.session = None
            self._stack = None
            self.tools = []
            return False

    async def disconnect(self):
        """断开连接。"""
        stack = self._stack
        self._stack = None
        self.session = None
        self.tools = []
        if stack is None:
            return
        try:
            await stack.aclose()
        except Exception as exc:
            # Preserve original error if still present, otherwise record cleanup failure.
            if not self.error:
                self.error = f"disconnect failed: {exc}"

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """调用 MCP Server 上的工具。"""
        if not self.session:
            return {"content": "", "error": "MCP Server 未连接"}
        try:
            result = await asyncio.wait_for(
                self.session.call_tool(tool_name, arguments or {}),
                timeout=_MCP_TOOL_TIMEOUT,
            )
            texts = []
            for content in result.content:
                if hasattr(content, "text"):
                    texts.append(content.text)
                else:
                    texts.append(str(content))
            return {"content": "\n".join(texts), "error": ""}
        except asyncio.TimeoutError:
            return {"content": "", "error": f"工具调用超时 ({_MCP_TOOL_TIMEOUT}s): {tool_name}"}
        except Exception as e:
            return {"content": "", "error": str(e)}

    async def ping(self) -> bool:
        """发送 ping 验证连接是否存活。"""
        if not self.session:
            return False
        try:
            await asyncio.wait_for(self.session.send_ping(), timeout=5)
            return True
        except Exception:
            return False

    def is_connected(self) -> bool:
        return self.session is not None
