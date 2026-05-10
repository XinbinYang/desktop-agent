import yaml
from pathlib import Path
from typing import Dict, List, Optional

from app.mcp.models import McpServerConfig, McpServerStatus, McpToolInfo
from app.mcp.client import MCPClientWrapper

MCP_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "mcp.yaml"


class McpManager:
    """MCP 连接管理器：管理多个 MCP Server 的生命周期。"""

    def __init__(self):
        self._clients: Dict[str, MCPClientWrapper] = {}
        self._configs: Dict[str, McpServerConfig] = {}
        self._load_configs()

    def _load_configs(self):
        """从 config/mcp.yaml 加载配置。"""
        self._configs = {}
        if not MCP_CONFIG_PATH.exists():
            return
        try:
            with open(MCP_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for server_id, cfg in data.get("servers", {}).items():
                self._configs[server_id] = McpServerConfig(
                    id=server_id,
                    transport=cfg.get("transport", "stdio"),
                    command=cfg.get("command"),
                    args=cfg.get("args", []),
                    url=cfg.get("url"),
                    env=cfg.get("env"),
                    enabled=cfg.get("enabled", True),
                )
        except Exception as e:
            print(f"[MCP] Failed to load config: {e}")

    async def reload_configs(self):
        """重新加载配置，断开已从配置中移除的服务器。"""
        old_ids = set(self._configs.keys())
        self._load_configs()
        new_ids = set(self._configs.keys())
        removed = old_ids - new_ids
        for sid in removed:
            await self.disconnect(sid)

    def list_servers(self) -> List[McpServerStatus]:
        """列出所有配置的 MCP Server 及其状态。"""
        result = []
        for sid, cfg in self._configs.items():
            client = self._clients.get(sid)
            result.append(McpServerStatus(
                id=sid,
                config=cfg,
                connected=client.is_connected() if client else False,
                tools=client.tools if client else [],
                error=client.error if client else None,
            ))
        return result

    def get_server(self, server_id: str) -> Optional[McpServerStatus]:
        for s in self.list_servers():
            if s.id == server_id:
                return s
        return None

    async def connect(self, server_id: str) -> bool:
        """连接到指定 MCP Server。"""
        cfg = self._configs.get(server_id)
        if not cfg:
            return False
        if not cfg.enabled:
            return False
        # 断开已有连接
        await self.disconnect(server_id)
        client = MCPClientWrapper(cfg)
        success = await client.connect()
        if success:
            self._clients[server_id] = client
        return success

    async def disconnect(self, server_id: str):
        """断开指定 MCP Server。"""
        client = self._clients.pop(server_id, None)
        if client:
            await client.disconnect()

    async def disconnect_all(self):
        """断开所有 MCP Server。"""
        for client in list(self._clients.values()):
            await client.disconnect()
        self._clients.clear()

    async def check_health(self) -> dict:
        """检查所有已连接服务器的健康状态，标记断连的服务器。
        返回健康检查结果摘要。"""
        dead = []
        alive = []
        for sid, client in list(self._clients.items()):
            if await client.ping():
                alive.append(sid)
            else:
                dead.append(sid)
                await self.disconnect(sid)
        return {"alive": alive, "dead": dead}

    async def call_tool(self, server_id: str, tool_name: str, arguments: dict) -> dict:
        """调用指定 Server 上的工具。"""
        client = self._clients.get(server_id)
        if not client:
            return {"content": "", "error": f"MCP Server '{server_id}' 未连接"}
        return await client.call_tool(tool_name, arguments)

    def get_all_tools(self) -> List[McpToolInfo]:
        """获取所有已连接 Server 的工具列表。"""
        tools = []
        for server_id, client in self._clients.items():
            if client.is_connected():
                for t in client.tools:
                    tools.append(McpToolInfo(
                        name=f"mcp_{server_id}_{t.name}",
                        description=f"[MCP:{server_id}] {t.description}",
                        parameters=t.parameters,
                    ))
        return tools


# 全局单例
_mcp_manager: Optional[McpManager] = None


def get_mcp_manager() -> McpManager:
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = McpManager()
    return _mcp_manager
