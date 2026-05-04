"""Shared message utilities for AgentSession and WorkerSession."""
import inspect
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


def trim_messages(
    messages: List[Dict[str, Any]],
    max_messages: int,
    build_system_prompt_fn: Optional[Callable[[], str]] = None,
    validate_tool_ids: bool = False,
) -> List[Dict[str, Any]]:
    """Trim message history preserving tool_call/tool_result groupings.

    Args:
        messages: Full message list.
        max_messages: Maximum number of messages to keep (excluding system prompt).
        build_system_prompt_fn: If provided, called to rebuild system prompt when the
            first message is not a system message, or when the system prompt needs refreshing.
        validate_tool_ids: If True, verify that tool_call IDs in the assistant message
            match the tool_call_id in following tool messages. Orphaned tool_calls
            are sanitized (tool_calls removed from the assistant message).

    Returns:
        Trimmed messages list (new list, not mutated in place).
    """
    if not messages:
        return []

    first = messages[0]
    has_system = first.get("role") == "system"

    system_msg = first if has_system else {}
    body = messages[1:] if has_system else list(messages)

    groups: List[List[Dict[str, Any]]] = []
    i = 0
    while i < len(body):
        msg = body[i]
        role = msg.get("role")

        if role == "tool":
            i += 1
            continue

        if role == "assistant" and msg.get("tool_calls"):
            group = [msg]

            if validate_tool_ids:
                expected_ids = {
                    tc.get("id", "")
                    for tc in msg.get("tool_calls", [])
                    if tc.get("id")
                }
                seen_ids: set[str] = set()
                i += 1
                while i < len(body) and body[i].get("role") == "tool":
                    tool_msg = body[i]
                    tool_call_id = tool_msg.get("tool_call_id", "")
                    if not expected_ids or tool_call_id in expected_ids:
                        group.append(tool_msg)
                        if tool_call_id:
                            seen_ids.add(tool_call_id)
                    i += 1

                if expected_ids and seen_ids != expected_ids:
                    sanitized = dict(msg)
                    sanitized.pop("tool_calls", None)
                    group = [sanitized]
            else:
                i += 1
                while i < len(body) and body[i].get("role") == "tool":
                    group.append(body[i])
                    i += 1

            groups.append(group)
            continue

        groups.append([msg])
        i += 1

    selected: List[List[Dict[str, Any]]] = []
    count = 0
    for group in reversed(groups):
        if selected and count + len(group) > max_messages:
            break
        selected.insert(0, group)
        count += len(group)

    if has_system:
        return [system_msg] + [msg for group in selected for msg in group]
    else:
        return [msg for group in selected for msg in group]


@dataclass
class ToolCallResult:
    """Result of executing a single tool call."""
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    tool_call_id: str = ""
    result_text: str = ""
    duration_ms: int = 0
    error: Optional[str] = None
    base64_image: Optional[str] = None


def parse_tool_args(raw_args: Any) -> Tuple[dict, Optional[str]]:
    """Parse tool call arguments from JSON string or dict.

    Returns:
        (parsed_args, error_text). error_text is None on success.
    """
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        if not isinstance(args, dict):
            raise ValueError("tool arguments must be a JSON object")
        return args, None
    except (TypeError, ValueError, json.JSONDecodeError) as e:
        return {}, f"[ERROR] Tool argument parse failed: {e}"


async def execute_tool(
    tool_name: str,
    tool_args: dict,
    allowed_tools: List[str],
    session_id: str = "",
    get_tool_fn: Callable = None,
) -> ToolCallResult:
    """Execute a single tool call with validation and timing.

    Args:
        tool_name: Name of the tool to execute.
        tool_args: Parsed arguments for the tool.
        allowed_tools: List of allowed tool names. If tool_name is not in this list, returns an error.
        session_id: If provided, injected into tool_args if the tool accepts it.
        get_tool_fn: Function to retrieve a tool by name. Defaults to app.tools.get_tool.

    Returns:
        ToolCallResult with execution output.
    """
    if get_tool_fn is None:
        from app.tools import get_tool
        get_tool_fn = get_tool

    if tool_name not in allowed_tools:
        return ToolCallResult(
            tool_name=tool_name,
            tool_args=tool_args,
            result_text=f"[ERROR] Unknown tool: {tool_name}",
            error=f"Unknown tool: {tool_name}",
        )

    try:
        tool = get_tool_fn(tool_name)
    except (KeyError, Exception):
        return ToolCallResult(
            tool_name=tool_name,
            tool_args=tool_args,
            result_text=f"[ERROR] Unknown tool: {tool_name}",
            error=f"Unknown tool: {tool_name}",
        )

    if "session_id" in inspect.signature(tool.execute).parameters and "session_id" not in tool_args:
        tool_args["session_id"] = session_id

    try:
        started_at = time.time()
        result = await tool.execute(**tool_args)
        duration_ms = round((time.time() - started_at) * 1000)
        return ToolCallResult(
            tool_name=tool_name,
            tool_args=tool_args,
            result_text=result.to_text(),
            duration_ms=duration_ms,
            base64_image=result.base64_image,
        )
    except Exception as e:
        return ToolCallResult(
            tool_name=tool_name,
            tool_args=tool_args,
            result_text=f"[ERROR] Tool execution failed: {e}",
            error=str(e),
        )
