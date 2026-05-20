"""Shared runtime for Codex-like browser/desktop automation."""
from __future__ import annotations

import base64
import io
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from PIL import Image

from app.runtime_paths import runtime_dir


MAX_SCREENSHOT_SIZE = (1600, 900)
MAX_TRACE_SNAPSHOTS = 2

_LATEST_SNAPSHOT_BY_SESSION: dict[str, dict[str, Any]] = {}


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def automation_session_dir(session_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (session_id or "default"))
    path = runtime_dir("automation") / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _image_to_png_base64(img: Image.Image) -> tuple[str, int, int]:
    img = img.convert("RGB")
    width, height = img.size
    img.thumbnail(MAX_SCREENSHOT_SIZE, Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return base64.b64encode(out.getvalue()).decode("utf-8"), img.size[0], img.size[1]


def encode_image_bytes(image_bytes: bytes) -> tuple[str, int, int]:
    return _image_to_png_base64(Image.open(io.BytesIO(image_bytes)))


def encode_pil_image(img: Image.Image) -> tuple[str, int, int]:
    return _image_to_png_base64(img)


def save_snapshot(session_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(snapshot)
    snapshot_id = snapshot.get("snapshot_id") or new_id("snap")
    snapshot["snapshot_id"] = snapshot_id
    snapshot.setdefault("session_id", session_id or "default")
    snapshot.setdefault("timestamp", now_ms())

    screenshot = snapshot.get("screenshot") or {}
    b64 = screenshot.get("base64")
    if b64:
        png_path = automation_session_dir(session_id) / f"{snapshot_id}.png"
        try:
            png_path.write_bytes(base64.b64decode(b64))
            screenshot["path"] = str(png_path)
        except Exception:
            pass
        snapshot["screenshot"] = screenshot

    _LATEST_SNAPSHOT_BY_SESSION[session_id or "default"] = snapshot
    return snapshot


def latest_snapshot(session_id: str) -> Optional[dict[str, Any]]:
    return _LATEST_SNAPSHOT_BY_SESSION.get(session_id or "default")


def snapshot_for_trace(snapshot: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not snapshot:
        return None
    copy = dict(snapshot)
    screenshot = dict(copy.get("screenshot") or {})
    screenshot.pop("base64", None)
    copy["screenshot"] = screenshot
    copy["elements"] = list(copy.get("elements") or [])[:MAX_TRACE_SNAPSHOTS]
    return copy


def find_element(snapshot: Optional[dict[str, Any]], element_id: str) -> Optional[dict[str, Any]]:
    if not snapshot or not element_id:
        return None
    for element in snapshot.get("elements") or []:
        if element.get("id") == element_id:
            return element
    return None


def save_trace(session_id: str, trace: dict[str, Any]) -> dict[str, Any]:
    trace = dict(trace)
    trace_id = trace.get("trace_id") or new_id("trace")
    trace["trace_id"] = trace_id
    trace.setdefault("session_id", session_id or "default")
    trace.setdefault("created_at", now_ms())
    trace["updated_at"] = now_ms()
    path = automation_session_dir(session_id) / f"{trace_id}.json"
    trace["path"] = str(path)
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    return trace


def load_trace(session_id: str, trace_id: str) -> Optional[dict[str, Any]]:
    if not trace_id:
        return None
    path = automation_session_dir(session_id) / f"{trace_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def summarize_elements(elements: Iterable[dict[str, Any]], limit: int = 12) -> str:
    lines: List[str] = []
    for element in list(elements)[:limit]:
        label = element.get("name") or element.get("text") or element.get("role") or element.get("id")
        bbox = element.get("bbox") or {}
        lines.append(
            f"- {element.get('id')}: {label} "
            f"@ ({bbox.get('x')},{bbox.get('y')},{bbox.get('width')}x{bbox.get('height')})"
        )
    return "\n".join(lines)
