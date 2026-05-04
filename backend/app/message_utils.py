"""Shared message utilities for AgentSession and WorkerSession."""
from typing import Any, Callable, Dict, List, Optional


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
