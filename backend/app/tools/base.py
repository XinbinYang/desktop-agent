from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

class ToolResult:
    def __init__(
        self,
        output: str = "",
        error: str = "",
        base64_image: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.output = output
        self.error = error
        self.base64_image = base64_image
        self.metadata = metadata or {}
    
    def to_text(self) -> str:
        if self.error:
            return f"[ERROR] {self.error}"
        return self.output

class BaseTool(ABC):
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}
    
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        pass
    
    def get_openai_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }
    
    def get_anthropic_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters
        }
