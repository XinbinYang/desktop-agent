from __future__ import annotations

from contextlib import suppress
from typing import Dict, List, Set

from fastapi import WebSocket


SESSION_DELETED_CLOSE_CODE = 4004
SESSION_DELETED_REASON = "Session deleted"

_connections: Dict[str, Set[WebSocket]] = {}
_deleted_session_ids: Set[str] = set()


def mark_session_deleted(session_id: str) -> None:
    _deleted_session_ids.add(session_id)


def allow_session_recreate(session_id: str) -> None:
    _deleted_session_ids.discard(session_id)


def is_session_deleted(session_id: str) -> bool:
    return session_id in _deleted_session_ids


def register_session_websocket(session_id: str, websocket: WebSocket) -> None:
    _connections.setdefault(session_id, set()).add(websocket)


def unregister_session_websocket(session_id: str, websocket: WebSocket) -> None:
    sockets = _connections.get(session_id)
    if not sockets:
        return
    sockets.discard(websocket)
    if not sockets:
        _connections.pop(session_id, None)


async def close_session_websockets(
    session_id: str,
    *,
    code: int = SESSION_DELETED_CLOSE_CODE,
    reason: str = SESSION_DELETED_REASON,
) -> int:
    sockets = list(_connections.pop(session_id, set()))
    for websocket in sockets:
        with suppress(Exception):
            await websocket.close(code=code, reason=reason)
    return len(sockets)


def session_websocket_snapshot() -> List[dict]:
    return [
        {"session_id": session_id, "connections": len(sockets)}
        for session_id, sockets in sorted(_connections.items())
    ]
