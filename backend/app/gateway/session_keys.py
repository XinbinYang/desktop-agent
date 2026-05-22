from __future__ import annotations

from app.connectors.base import _safe_session_part
from app.gateway.envelope import MessageEnvelope


def build_session_id(
    envelope: MessageEnvelope,
    connector_name: str,
    target_agent: str,
) -> str:
    """Compose a session_id for a gateway-dispatched message.

    Layout (back-compat with PlatformConnector.get_session_id):
        <connector>_<target_agent>_<user>[_<channel>][_t<thread>]

    Adds a `_t<thread>` suffix only when a thread / reply root is present,
    so existing channel-level sessions remain stable when no thread exists.
    """
    parts = [
        _safe_session_part(connector_name),
        _safe_session_part(target_agent),
        _safe_session_part(envelope.user_id),
    ]
    if envelope.channel_id:
        parts.append(_safe_session_part(envelope.channel_id))
    session_id = "_".join(parts)
    thread_key = envelope.thread_id or envelope.reply_to or ""
    if thread_key:
        session_id = f"{session_id}_t{_safe_session_part(thread_key)}"
    return session_id
