"""On-disk store for large tool artifacts (screenshots, charts, files).

Long-running sessions otherwise inline base64 image payloads directly into
``AgentSession.messages``, which keeps every screenshot resident in Python
memory and bloats the persisted session JSON. This module spills large
payloads to disk and lets the rest of the system reference them by id/url so
the transcript only carries lightweight metadata.
"""

from __future__ import annotations

import base64
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from app.runtime_paths import runtime_dir

logger = logging.getLogger(__name__)

# Decoded payloads at or above this size are spilled to disk and replaced with
# a reference. Smaller ones stay inline — a file + HTTP round-trip is not worth
# it for tiny icons.
INLINE_SPILL_THRESHOLD_BYTES = 32 * 1024

_MIME_BY_EXT: Dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
    "bin": "application/octet-stream",
}
_EXT_BY_MIME: Dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}


def _safe_token(value: str) -> str:
    return "".join(c for c in str(value) if c.isalnum() or c in "-_")


def _artifacts_root() -> Path:
    return runtime_dir("artifacts")


def _session_dir(session_id: str, *, create: bool = True) -> Path:
    directory = _artifacts_root() / (_safe_token(session_id) or "_")
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def _ext_for_mime(mime_type: str) -> str:
    return _EXT_BY_MIME.get((mime_type or "").lower().strip(), "bin")


def should_externalize(base64_data: str) -> bool:
    """True when a base64 payload is large enough to be worth spilling to disk."""
    if not isinstance(base64_data, str) or not base64_data:
        return False
    # Decoded size is ~3/4 of the base64 character count.
    return (len(base64_data) * 3) // 4 >= INLINE_SPILL_THRESHOLD_BYTES


def store_base64(
    session_id: str,
    artifact_id: str,
    base64_data: str,
    mime_type: str,
) -> Optional[Dict[str, Any]]:
    """Persist a base64 payload to disk.

    Returns ``{"size": int, "filename": str}`` on success, or ``None`` if the
    payload could not be decoded or written (caller should keep it inline).
    """
    try:
        raw = base64.b64decode(base64_data, validate=False)
    except Exception:
        logger.warning("artifact_store: could not decode base64 for %s", artifact_id)
        return None
    safe_id = _safe_token(artifact_id) or "artifact"
    ext = _ext_for_mime(mime_type)
    path = _session_dir(session_id) / f"{safe_id}.{ext}"
    try:
        path.write_bytes(raw)
    except OSError:
        logger.warning("artifact_store: could not write %s", path)
        return None
    return {"size": len(raw), "filename": path.name}


def load(session_id: str, artifact_id: str) -> Optional[Tuple[bytes, str]]:
    """Return ``(bytes, mime_type)`` for an externalized artifact, or ``None``."""
    safe_id = _safe_token(artifact_id)
    if not safe_id:
        return None
    directory = _session_dir(session_id, create=False)
    if not directory.is_dir():
        return None
    for path in directory.glob(f"{safe_id}.*"):
        try:
            data = path.read_bytes()
        except OSError:
            return None
        mime = _MIME_BY_EXT.get(path.suffix.lstrip(".").lower(), "application/octet-stream")
        return data, mime
    return None


def delete_session_artifacts(session_id: str) -> None:
    """Remove every externalized artifact for a session (best effort)."""
    directory = _session_dir(session_id, create=False)
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)
