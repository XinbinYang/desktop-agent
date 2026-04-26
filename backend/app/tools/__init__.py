from app.tools.base import BaseTool, ToolResult
from app.tools.file_tool import (
    FileReadTool, FileWriteTool, FileListTool, 
    FileSearchTool, FileDeleteTool
)
from app.tools.shell_tool import ShellExecuteTool, ShellStartTool
from app.tools.browser_tool import (
    BrowserNavigateTool, BrowserClickTool, BrowserTypeTool,
    BrowserScreenshotTool, BrowserEvaluateTool, BrowserCloseTool
)
from app.tools.desktop_tool import (
    ScreenshotTool, MouseClickTool, MouseMoveTool,
    TypeTextTool, PressKeyTool, ScrollTool, GetScreenSizeTool
)
from app.tools.app_tool import (
    AppOpenTool, AppListWindowsTool, AppFindWindowTool,
    AppClickTool, AppTypeTool
)

# 全局工具注册表
ALL_TOOLS: list[BaseTool] = [
    # 文件工具
    FileReadTool(),
    FileWriteTool(),
    FileListTool(),
    FileSearchTool(),
    FileDeleteTool(),
    # 终端工具
    ShellExecuteTool(),
    ShellStartTool(),
    # 浏览器工具
    BrowserNavigateTool(),
    BrowserClickTool(),
    BrowserTypeTool(),
    BrowserScreenshotTool(),
    BrowserEvaluateTool(),
    BrowserCloseTool(),
    # 桌面操控工具
    ScreenshotTool(),
    MouseClickTool(),
    MouseMoveTool(),
    TypeTextTool(),
    PressKeyTool(),
    ScrollTool(),
    GetScreenSizeTool(),
    # 应用控制工具
    AppOpenTool(),
    AppListWindowsTool(),
    AppFindWindowTool(),
    AppClickTool(),
    AppTypeTool(),
]

TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}

def get_tool_schemas() -> list[dict]:
    """获取所有工具的 OpenAI function schema"""
    return [t.get_openai_schema() for t in ALL_TOOLS]

def get_tool(name: str) -> BaseTool:
    return TOOLS_BY_NAME[name]

def list_tool_names() -> list[str]:
    return list(TOOLS_BY_NAME.keys())