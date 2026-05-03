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
from app.tools.wind_tool import (
    WindWsdTool, WindWssTool, WindWsetTool,
    WindEdbTool, WindTdaysTool
)
from app.tools.backtest_tool import (
    StrategyListTool, BacktestRunTool, BacktestReportTool
)
from app.tools.wind_sync_tool import WindSyncTool
from app.tools.git_tool import (
    GitCloneTool, GitStatusTool, GitCommitTool,
    GitPullTool, GitPushTool, GitBranchTool, GitRemoteTool
)
from app.tools.knowledge_tool import (
    KnowledgeIndexTool, KnowledgeSearchTool, KnowledgeListTool
)
from app.tools.workflow_tool import (
    WorkflowRecordTool, WorkflowStopTool, WorkflowListTool, WorkflowRunTool
)
from app.tools.worker_tool import DispatchWorkerTool, DispatchParallelTool

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
    # WIND 金融数据工具
    WindWsdTool(),
    WindWssTool(),
    WindWsetTool(),
    WindEdbTool(),
    WindTdaysTool(),
    # 策略回测工具
    StrategyListTool(),
    BacktestRunTool(),
    BacktestReportTool(),
    # WIND 数据同步工具
    WindSyncTool(),
    # Git 工具
    GitCloneTool(),
    GitStatusTool(),
    GitCommitTool(),
    GitPullTool(),
    GitPushTool(),
    GitBranchTool(),
    GitRemoteTool(),
    # 知识库工具
    KnowledgeIndexTool(),
    KnowledgeSearchTool(),
    KnowledgeListTool(),
    # 工作流工具
    WorkflowRecordTool(),
    WorkflowStopTool(),
    WorkflowListTool(),
    WorkflowRunTool(),
    # Worker 派发工具
    DispatchWorkerTool(),
    DispatchParallelTool(),
]

TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}


class DynamicToolRegistry:
    """动态工具注册表：用于 MCP 等运行时扩展的工具。"""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_schemas(self) -> list[dict]:
        return [t.get_openai_schema() for t in self._tools.values()]

    def clear(self):
        self._tools.clear()


def get_tool_schemas(dynamic_registry: DynamicToolRegistry | None = None) -> list[dict]:
    """获取所有工具的 OpenAI function schema（含动态工具）"""
    schemas = [t.get_openai_schema() for t in ALL_TOOLS]
    if dynamic_registry:
        schemas.extend(dynamic_registry.get_schemas())
    return schemas


def get_tool(name: str, dynamic_registry: DynamicToolRegistry | None = None) -> BaseTool:
    if name in TOOLS_BY_NAME:
        return TOOLS_BY_NAME[name]
    if dynamic_registry:
        tool = dynamic_registry.get(name)
        if tool:
            return tool
    raise KeyError(f"Tool not found: {name}")


def list_tool_names(dynamic_registry: DynamicToolRegistry | None = None) -> list[str]:
    names = list(TOOLS_BY_NAME.keys())
    if dynamic_registry:
        names.extend(dynamic_registry.list_names())
    return names


def get_static_tool_schemas() -> list[dict]:
    """获取静态工具的 OpenAI function schema"""
    return [t.get_openai_schema() for t in ALL_TOOLS]


def get_static_tool(name: str) -> BaseTool:
    return TOOLS_BY_NAME[name]


def list_static_tool_names() -> list[str]:
    return list(TOOLS_BY_NAME.keys())