"""
Tool: ``team_context`` — read or write the shared team context file.

:param action: ``"read"`` to fetch the current context, ``"write"`` to append.
:param content: The text to append (only required for ``"write"``).
:param team_id:  (internal) provided by the Agent session, not by the model.
"""

from .base import BaseTool, ToolResult


class TeamContextTool(BaseTool):
    name = "team_context"
    description = "Read or write the shared team context. Use 'read' to see what other team members have written. Use 'write' to share your progress, findings, or requests with the team."

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "write"],
                "description": "Whether to read the current context or write new content.",
            },
            "content": {
                "type": "string",
                "description": "The text to append to the team context. Required for 'write'.",
            },
        },
        "required": ["action"],
    }

    # Set per-session by the AgentSession before tool execution
    team_id: str | None = None
    team_name: str = ""

    async def execute(self, action: str, content: str = "", **kwargs) -> ToolResult:
        from ..teams import read_team_context, append_team_context

        if action == "read":
            ctx = read_team_context(self.team_id) if self.team_id else ""
            if ctx:
                return ToolResult(output=f"## Team 共享上下文 ({self.team_name})\n\n{ctx}")
            return ToolResult(output="Team 共享上下文当前为空。使用 write 来分享你的进展。")
        elif action == "write":
            if not self.team_id:
                return ToolResult(error="team_context: 当前会话未关联任何 Team。")
            if not content.strip():
                return ToolResult(error="team_context write: content 不能为空。")
            append_team_context(self.team_id, content)
            return ToolResult(output=f"已将内容写入 Team「{self.team_name}」的共享上下文。所有团队成员将在下一轮对话中看到此更新。")
        else:
            return ToolResult(error=f"team_context: 未知 action '{action}'。请使用 'read' 或 'write'。")


def create_team_context_tool(team_id: str | None, team_name: str = "") -> TeamContextTool:
    """Factory that binds team id/name to the tool instance."""
    tool = TeamContextTool()
    tool.team_id = team_id
    tool.team_name = team_name
    return tool
