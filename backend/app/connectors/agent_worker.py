import asyncio
import json
import sys
from typing import Any, Dict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


async def _run(payload: Dict[str, Any]) -> Dict[str, Any]:
    from app.agent import get_or_create_session

    session = get_or_create_session(
        str(payload["session_id"]),
        str(payload["model_id"]),
        role_id=str(payload["role_id"]),
        agent_type=str(payload["agent_type"]),
    )
    max_iterations = payload.get("max_iterations")
    if isinstance(max_iterations, int) and max_iterations > 0:
        session.max_iterations = min(session.max_iterations, max_iterations)
    thinking_intensity = str(payload.get("thinking_intensity") or "").strip().lower()
    if thinking_intensity not in {"low", "medium", "high"}:
        thinking_intensity = ""
    content_parts: list[str] = []
    errors: list[str] = []
    async for event in session.run(
        str(payload["prompt"]),
        None,
        thinking_intensity=thinking_intensity or None,
    ):
        event_type = event.get("type")
        data = event.get("data") or {}
        if event_type == "content":
            content_parts.append(str(data.get("text", "")))
        elif event_type == "error":
            errors.append(str(data.get("message", "") or data))

    content = "".join(content_parts).strip()
    return {
        "ok": True,
        "content": content,
        "errors": errors,
    }


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        result = asyncio.run(_run(payload))
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    sys.stdout.write("__DESKTOP_AGENT_RESULT__" + json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
