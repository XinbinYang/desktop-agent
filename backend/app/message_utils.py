"""Shared message utilities for AgentSession and WorkerSession."""
import inspect
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


DEFAULT_INTERRUPTED_TOOL_RESULT = (
    "[ERROR] Tool call interrupted before returning a result. "
    "The previous agent run was cancelled, disconnected, or superseded."
)


def _tool_call_name(tool_call: Dict[str, Any]) -> str:
    function = tool_call.get("function") or {}
    return str(function.get("name") or "")


def _tool_call_ids(tool_calls: Any) -> List[str]:
    if not isinstance(tool_calls, list):
        return []
    ids: List[str] = []
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            continue
        tool_call_id = str(tool_call.get("id") or "")
        if tool_call_id and tool_call_id not in ids:
            ids.append(tool_call_id)
    return ids


def repair_tool_call_messages(
    messages: List[Dict[str, Any]],
    missing_tool_content: str = DEFAULT_INTERRUPTED_TOOL_RESULT,
) -> List[Dict[str, Any]]:
    """Return a provider-safe copy with complete assistant/tool groupings.

    OpenAI-compatible providers require every assistant message containing
    tool_calls to be followed immediately by one tool message for each
    tool_call_id. A run can be interrupted after the assistant tool_calls were
    persisted but before tool results were appended, leaving history that the
    next provider call rejects. This helper inserts synthetic interrupted tool
    results for missing ids and drops orphan tool messages.
    """
    repaired: List[Dict[str, Any]] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role")

        if role == "tool":
            i += 1
            continue

        tool_calls = msg.get("tool_calls")
        if role != "assistant" or not tool_calls:
            repaired.append(dict(msg))
            i += 1
            continue

        expected_ids = _tool_call_ids(tool_calls)
        assistant_msg = dict(msg)
        if not expected_ids:
            assistant_msg.pop("tool_calls", None)
            if str(assistant_msg.get("content") or "").strip() or str(assistant_msg.get("reasoning_content") or "").strip():
                repaired.append(assistant_msg)
            i += 1
            while i < len(messages) and messages[i].get("role") == "tool":
                i += 1
            continue

        repaired.append(assistant_msg)
        i += 1

        seen_ids: set[str] = set()
        tool_messages_by_id: Dict[str, Dict[str, Any]] = {}
        while i < len(messages) and messages[i].get("role") == "tool":
            tool_msg = dict(messages[i])
            tool_call_id = str(tool_msg.get("tool_call_id") or "")
            if tool_call_id in expected_ids and tool_call_id not in seen_ids:
                tool_messages_by_id[tool_call_id] = tool_msg
                seen_ids.add(tool_call_id)
            i += 1

        calls_by_id = {
            str(tool_call.get("id") or ""): tool_call
            for tool_call in tool_calls
            if isinstance(tool_call, dict) and tool_call.get("id")
        }
        for tool_call_id in expected_ids:
            if tool_call_id in tool_messages_by_id:
                repaired.append(tool_messages_by_id[tool_call_id])
                continue
            tool_call = calls_by_id.get(tool_call_id, {})
            repaired.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": _tool_call_name(tool_call),
                "content": missing_tool_content,
            })

    return repaired


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

    turns: List[List[Dict[str, Any]]] = []
    current_turn: List[Dict[str, Any]] = []
    current_checkpoint = object()

    for group in groups:
        first_msg = group[0] if group else {}
        role = first_msg.get("role")
        checkpoint = first_msg.get("checkpoint_id")

        if role == "user":
            starts_new_turn = (
                current_turn
                and any(m.get("role") == "user" for m in current_turn)
                and (checkpoint is None or checkpoint != current_checkpoint)
            )
            if starts_new_turn:
                turns.append(current_turn)
                current_turn = []
            current_turn.extend(group)
            current_checkpoint = checkpoint
            continue

        if current_turn:
            current_turn.extend(group)
        else:
            turns.append(group)

    if current_turn:
        turns.append(current_turn)

    selected: List[List[Dict[str, Any]]] = []
    count = 0
    for turn in reversed(turns):
        if selected and count + len(turn) > max_messages:
            break
        selected.insert(0, turn)
        count += len(turn)

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
    metadata: Dict[str, Any] = field(default_factory=dict)


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
    run_id: str = "",
    tool_call_id: str = "",
    worker_id: str = "",
    parent_tool_call_id: str = "",
    agent_type: str = "",
    session_model_id: str = "",
    get_tool_fn: Optional[Callable[..., Any]] = None,
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

    tool_params = inspect.signature(tool.execute).parameters
    context_args = {
        "session_id": session_id,
        "run_id": run_id,
        "tool_call_id": tool_call_id,
        "worker_id": worker_id,
        "parent_tool_call_id": parent_tool_call_id,
        "agent_type": agent_type,
        "session_model_id": session_model_id,
    }
    for key, value in context_args.items():
        if key in tool_params and value and (key == "session_model_id" or key not in tool_args):
            tool_args[key] = value

    guardrail_decisions: List[Dict[str, Any]] = []
    record_event_fn: Optional[Callable[[str, str, Dict[str, Any]], Any]] = None
    evaluate_pre_tool_fn: Optional[Callable[..., Dict[str, Any]]] = None
    evaluate_post_tool_fn: Optional[Callable[..., Optional[Dict[str, Any]]]] = None
    try:
        from app.coding_runs import record_event as _record_event
        from app.guardrails import evaluate_post_tool, evaluate_pre_tool

        record_event_fn = _record_event
        evaluate_pre_tool_fn = evaluate_pre_tool
        evaluate_post_tool_fn = evaluate_post_tool
    except Exception:
        pass

    if run_id and record_event_fn:
        try:
            record_event_fn(run_id, "tool_start", {
                "tool_name": tool_name,
                "tool_args": tool_args,
                "tool_call_id": tool_call_id,
                "worker_id": worker_id,
                "parent_tool_call_id": parent_tool_call_id,
                "session_id": session_id,
            })
        except Exception:
            pass

    if evaluate_pre_tool_fn:
        try:
            decision = evaluate_pre_tool_fn(
                tool_name,
                tool_args,
                run_id=run_id,
                tool_call_id=tool_call_id,
            )
            guardrail_decisions.append(decision)
            if run_id and record_event_fn:
                record_event_fn(run_id, "guardrail_decision", decision)
            if decision.get("decision") == "blocked":
                result_text = f"[GUARDRAIL_BLOCKED] {decision.get('reason', 'Tool use blocked')}"
                metadata = {"guardrail_decisions": guardrail_decisions}
                if run_id and record_event_fn:
                    record_event_fn(run_id, "tool_done", {
                        "tool_name": tool_name,
                        "tool_call_id": tool_call_id,
                        "duration_ms": 0,
                        "error": decision.get("reason", "Tool use blocked"),
                        "metadata": metadata,
                    })
                return ToolCallResult(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_call_id=tool_call_id,
                    result_text=result_text,
                    duration_ms=0,
                    error=decision.get("reason", "Tool use blocked"),
                    metadata=metadata,
                )
        except Exception:
            pass

    try:
        started_at = time.time()
        result = await tool.execute(**tool_args)
        duration_ms = round((time.time() - started_at) * 1000)
        metadata = dict(result.metadata or {})
        if evaluate_post_tool_fn:
            try:
                decision = evaluate_post_tool_fn(
                    tool_name,
                    result.to_text(),
                    metadata,
                    run_id=run_id,
                    tool_call_id=tool_call_id,
                )
                if decision:
                    guardrail_decisions.append(decision)
                    if run_id and record_event_fn:
                        record_event_fn(run_id, "guardrail_decision", decision)
            except Exception:
                pass
        if guardrail_decisions:
            metadata["guardrail_decisions"] = guardrail_decisions
        if run_id and record_event_fn:
            try:
                record_event_fn(run_id, "tool_done", {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "worker_id": worker_id,
                    "parent_tool_call_id": parent_tool_call_id,
                    "duration_ms": duration_ms,
                    "error": result.error,
                    "metadata": metadata,
                })
            except Exception:
                pass
        return ToolCallResult(
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
            result_text=result.to_text(),
            duration_ms=duration_ms,
            error=result.error or None,
            base64_image=result.base64_image,
            metadata=metadata,
        )
    except Exception as e:
        if run_id and record_event_fn:
            try:
                record_event_fn(run_id, "tool_done", {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "worker_id": worker_id,
                    "parent_tool_call_id": parent_tool_call_id,
                    "duration_ms": 0,
                    "error": str(e),
                    "metadata": {"guardrail_decisions": guardrail_decisions},
                })
            except Exception:
                pass
        return ToolCallResult(
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
            result_text=f"[ERROR] Tool execution failed: {e}",
            error=str(e),
            metadata={"guardrail_decisions": guardrail_decisions} if guardrail_decisions else {},
        )


# ── @Mention resolver ───────────────────────────────────────────────────────

_MENTION_PATTERN = re.compile(r"@(file|folder|git|knowledge):([^\s]+)")

def resolve_mentions(user_text: str, project_path: str = "") -> str:
    """Resolve @mentions in user input and prepend context.

    Supports:
      @file:relative/path  — reads file content and prepends it
      @folder:relative/path — lists directory contents
      @git                 — prepends git status info
      @knowledge:query     — searches RAG knowledge base
    """
    mentions = _MENTION_PATTERN.findall(user_text)
    if not mentions:
        return user_text

    context_parts: list[str] = []
    for mtype, mvalue in mentions:
        if mtype == "file" and project_path:
            try:
                fp = (Path(project_path) / mvalue).resolve()
                if fp.is_relative_to(Path(project_path).resolve()) and fp.is_file():
                    content = fp.read_text(encoding="utf-8", errors="replace")
                    if len(content) > 4000:
                        content = content[:4000] + "\n... (truncated)"
                    context_parts.append(f"## @file:{mvalue}\n```\n{content}\n```")
            except Exception:
                context_parts.append(f"[Could not read @file:{mvalue}]")

        elif mtype == "folder" and project_path:
            try:
                dp = (Path(project_path) / mvalue).resolve()
                if dp.is_relative_to(Path(project_path).resolve()) and dp.is_dir():
                    items = sorted(dp.iterdir())[:50]
                    listing = "\n".join(
                        f"- {p.name}{'/' if p.is_dir() else ''}" for p in items
                    )
                    context_parts.append(f"## @folder:{mvalue}\n{listing}")
            except Exception:
                context_parts.append(f"[Could not list @folder:{mvalue}]")

        elif mtype == "git" and project_path:
            import subprocess
            try:
                r = subprocess.run(
                    ["git", "status", "--short"],
                    cwd=project_path,
                    capture_output=True, text=True, timeout=10,
                    encoding="utf-8", errors="replace",
                )
                if r.returncode == 0:
                    context_parts.append(f"## @git status\n```\n{r.stdout.strip()[:2000]}\n```")
            except Exception:
                context_parts.append("[git status unavailable]")

        elif mtype == "knowledge":
            try:
                from app.rag.engine import get_rag_engine
                rag = get_rag_engine()
                results = rag.search(mvalue, top_k=3)
                relevant = [r for r in results if r.score >= 0.3]
                if relevant:
                    kctx = "\n".join(
                        f"### {r.source_path} (score: {r.score:.2f})\n{r.content[:600]}"
                        for r in relevant
                    )
                    context_parts.append(f"## @knowledge:{mvalue}\n{kctx}")
                else:
                    context_parts.append(f"[No knowledge results for: {mvalue}]")
            except Exception:
                context_parts.append(f"[Knowledge search failed for: {mvalue}]")

    if not context_parts:
        return user_text

    # Remove @mention syntax from the user-visible text
    clean_text = _MENTION_PATTERN.sub("", user_text).strip()
    context_block = "\n\n".join(context_parts)
    return f"{context_block}\n\n---\n\n{clean_text}"
