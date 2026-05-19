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
from app.tools.web_tool import WebSearchTool, WebFetchTool
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
    GitCloneTool, GitStatusTool, GitDiffTool, GitCommitTool,
    GitPullTool, GitPushTool, GitBranchTool, GitRemoteTool
)
from app.tools.knowledge_tool import (
    KnowledgeIndexTool, KnowledgeSearchTool, KnowledgeListTool, KnowledgeClearTool
)
from app.tools.workflow_tool import (
    WorkflowRecordTool, WorkflowStopTool, WorkflowListTool, WorkflowRunTool
)
from app.tools.worker_tool import DispatchWorkerTool, DispatchParallelTool
from app.tools.coding_tool import (
    RepoMapTool, CodeSearchTool, FileOutlineTool, FilePatchTool,
    VerifyProjectTool, RunReviewTool, WorktreeStatusTool,
)
from app.tools.plan_tool import PlanAskQuestionsTool, PlanWriteDraftTool, PlanUpdateTodosTool
from app.tools.test_tool import RunTestsTool
from app.tools.diagnostics_tool import ListDiagnosticsTool
from app.tools.ocr_tool import OCRClickTool, OCRFindTool, OCRReadTool
from app.tools.memory_tool import MemorySearchTool, MemoryHandoffTool, MemoryListTool
from app.tools.collaboration_tool import (
    ConsultCodingAgentTool,
    DelegateToCodingAgentTool,
    RequestPersonalContextTool,
)
from app.tools.skill_tool import (
    SkillArchiveTool,
    SkillDraftSaveTool,
    SkillListTool,
    SkillPublishTool,
    SkillReadTool,
    SkillValidateTool,
)

# 全局工具注册表
ALL_TOOLS: list[BaseTool] = [
    # 文件工具
    FileReadTool(),
    FileWriteTool(),
    FilePatchTool(),
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
    WebSearchTool(),
    WebFetchTool(),
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
    GitDiffTool(),
    GitCommitTool(),
    GitPullTool(),
    GitPushTool(),
    GitBranchTool(),
    GitRemoteTool(),
    # 知识库工具
    KnowledgeIndexTool(),
    KnowledgeSearchTool(),
    KnowledgeListTool(),
    KnowledgeClearTool(),
    # 工作流工具
    WorkflowRecordTool(),
    WorkflowStopTool(),
    WorkflowListTool(),
    WorkflowRunTool(),
    RepoMapTool(),
    CodeSearchTool(),
    FileOutlineTool(),
    VerifyProjectTool(),
    RunReviewTool(),
    WorktreeStatusTool(),
    # Worker 派发工具
    DispatchWorkerTool(),
    DispatchParallelTool(),
    # Plan mode 工具
    PlanAskQuestionsTool(),
    PlanWriteDraftTool(),
    PlanUpdateTodosTool(),
    RunTestsTool(),
    ListDiagnosticsTool(),
    OCRClickTool(),
    OCRFindTool(),
    OCRReadTool(),
    # 记忆管理工具
    MemorySearchTool(),
    MemoryHandoffTool(),
    MemoryListTool(),
    ConsultCodingAgentTool(),
    DelegateToCodingAgentTool(),
    RequestPersonalContextTool(),
    SkillDraftSaveTool(),
    SkillValidateTool(),
    SkillPublishTool(),
    SkillListTool(),
    SkillReadTool(),
    SkillArchiveTool(),
]

TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}

# ── Per-agent tool profiles ──

# Tools available to the Coding Agent (focused on development).
CODING_AGENT_TOOLS: frozenset[str] = frozenset({
    # File tools
    "file_read", "file_write", "file_patch", "file_list", "file_search", "file_delete",
    # Shell
    "shell_execute", "shell_start",
    # Git
    "git_clone", "git_status", "git_diff", "git_commit",
    "git_pull", "git_push", "git_branch", "git_remote",
    # Coding-specific
    "repo_map", "code_search", "file_outline",
    "verify_project", "run_review", "worktree_status",
    # Worker dispatch
    "dispatch_worker", "dispatch_parallel",
    # Collaboration
    "request_personal_context",
    # Skill authoring
    "skill_draft_save", "skill_validate", "skill_publish",
    "skill_list", "skill_read", "skill_archive",
    # Knowledge base
    "knowledge_search", "knowledge_list",
    # Web
    "web_search", "web_fetch",
    # Plan mode
    "plan_ask_questions", "plan_write_draft", "plan_update_todos",
    # Testing & diagnostics
    "run_tests", "list_diagnostics",
    # Screenshot / browser (for debugging UI)
    "screenshot", "browser_navigate", "browser_screenshot",
    "get_screen_size",
    # OCR (for reading error dialogs, etc.)
    "ocr_read", "ocr_click", "ocr_find",
})

# Personal Agent gets all tools (no filtering).
# Coding Agent is restricted to CODING_AGENT_TOOLS.


def _filter_tools_by_agent(agent_type: str | None) -> frozenset[str] | None:
    """Return the allowed tool name set for an agent type, or None for all tools."""
    if agent_type == "coding":
        return CODING_AGENT_TOOLS
    return None  # personal → all tools


# Tools the frontend may invoke via WebSocket `tool_direct`. Restricted to
# read-only or user-visible actions so a compromised renderer (or any process
# on localhost in dev mode) cannot call shell_execute / file_write / etc.
# without going through the agent.
SAFE_DIRECT_TOOLS: set[str] = {
    "screenshot",
    "get_screen_size",
    "browser_navigate",
    "browser_screenshot",
    "app_list_windows",
    "git_status",
    "knowledge_list",
}

# Tool categories for grouped presentation in the system prompt.
TOOL_CATEGORIES: dict[str, list[str]] = {
    "文件工具": ["file_read", "file_write", "file_patch", "file_list", "file_search", "file_delete"],
    "终端工具": ["shell_execute", "shell_start"],
    "浏览器工具": [
        "browser_navigate", "browser_click", "browser_type",
        "browser_screenshot", "browser_evaluate", "browser_close",
    ],
    "Web": ["web_search", "web_fetch"],
    "桌面操控": [
        "screenshot", "mouse_click", "mouse_move", "type_text",
        "press_key", "scroll", "get_screen_size",
    ],
    "应用控制": ["app_open", "app_list_windows", "app_find_window", "app_click", "app_type"],
    "Git 版本控制": [
        "git_clone", "git_status", "git_diff", "git_commit",
        "git_pull", "git_push", "git_branch", "git_remote",
    ],
    "知识库": ["knowledge_index", "knowledge_search", "knowledge_list", "knowledge_clear"],
    "WIND 金融数据": ["wind_wsd", "wind_wss", "wind_wset", "wind_edb", "wind_tdays", "wind_sync"],
    "策略回测": ["strategy_list", "backtest_run", "backtest_report"],
    "工作流": ["workflow_record", "workflow_stop", "workflow_list", "workflow_run"],
    "Coding Agent": [
        "repo_map", "code_search", "file_outline",
        "verify_project", "run_review", "worktree_status",
    ],
    "Worker 派发": ["dispatch_worker", "dispatch_parallel"],
    "Agent Collaboration": ["consult_coding_agent", "delegate_to_coding_agent", "request_personal_context"],
    "Plan Mode": ["plan_ask_questions", "plan_write_draft", "plan_update_todos"],
    "Skill Authoring": [
        "skill_draft_save", "skill_validate", "skill_publish",
        "skill_list", "skill_read", "skill_archive",
    ],
    "记忆管理": ["memory_search", "memory_list", "memory_handoff_write"],
}


def build_tools_description(dynamic_registry: "DynamicToolRegistry | None" = None, agent_type: str | None = None) -> str:
    """构建按类别分组的工具描述文本。支持 per-agent 过滤。"""
    allowed = _filter_tools_by_agent(agent_type)
    categorized: dict[str, list[str]] = {cat: [] for cat in TOOL_CATEGORIES}
    uncategorized: list[str] = []
    handled: set[str] = set()

    all_schemas = get_tool_schemas(dynamic_registry, agent_type=agent_type)
    for t in all_schemas:
        name = t["function"]["name"]
        desc = t["function"]["description"]
        line = f"- {name}: {desc}"
        placed = False
        for cat, names in TOOL_CATEGORIES.items():
            if name in names:
                categorized[cat].append(line)
                handled.add(name)
                placed = True
                break
        if not placed:
            uncategorized.append(line)

    parts = []
    for cat, lines in categorized.items():
        if lines:
            # Skip categories that are empty for coding agent
            if allowed and not any(name in allowed for name in TOOL_CATEGORIES.get(cat, [])):
                continue
            parts.append(f"### {cat}\n" + "\n".join(lines))

    if uncategorized:
        prefix = "### MCP 外部工具\n" if dynamic_registry else "### 其他工具\n"
        parts.append(prefix + "\n".join(uncategorized))

    return "\n\n".join(parts)


class DynamicToolRegistry:
    """动态工具注册表：用于 MCP 等运行时扩展的工具。"""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_schemas(self) -> list[dict]:
        return [t.get_openai_schema() for t in self._tools.values()]

    def clear(self):
        self._tools.clear()


def get_tool_schemas(dynamic_registry: DynamicToolRegistry | None = None, agent_type: str | None = None) -> list[dict]:
    """获取所有工具的 OpenAI function schema（含动态工具），支持 per-agent 过滤。"""
    allowed = _filter_tools_by_agent(agent_type)
    if allowed:
        schemas = [t.get_openai_schema() for t in ALL_TOOLS if t.name in allowed]
    else:
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
