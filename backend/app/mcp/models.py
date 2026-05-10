from pydantic import BaseModel
from typing import Literal, Optional, Dict, Any, List


class McpServerConfig(BaseModel):
    id: str
    transport: Literal["stdio", "sse"]
    command: Optional[str] = None
    args: List[str] = []
    url: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    enabled: bool = True


class McpToolInfo(BaseModel):
    name: str
    description: str
    parameters: dict


class McpServerStatus(BaseModel):
    id: str
    config: McpServerConfig
    connected: bool = False
    tools: List[McpToolInfo] = []
    error: Optional[str] = None
