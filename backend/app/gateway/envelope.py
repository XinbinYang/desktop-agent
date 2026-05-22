from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class MessageEnvelope:
    platform: str
    channel_id: str
    user_id: str
    text: str
    thread_id: str = ""
    reply_to: Optional[str] = None
    sender_name: str = ""
    is_dm: bool = False
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    raw_meta: Dict[str, Any] = field(default_factory=dict)

    def context_prefix(self) -> str:
        lines = [f"[{self.platform} message]"]
        if self.sender_name:
            lines.append(f"Sender: {self.sender_name} ({self.user_id})")
        else:
            lines.append(f"Sender: {self.user_id}")
        lines.append(f"Channel: {self.channel_id}")
        if self.is_dm:
            lines.append("Chat type: dm")
        if self.thread_id:
            lines.append(f"Thread: {self.thread_id}")
        if self.reply_to:
            lines.append(f"In reply to: {self.reply_to}")
        for key, value in self.raw_meta.items():
            if key in {"sender_name", "channel_id", "thread_id"}:
                continue
            lines.append(f"{key}: {value}")
        return "\n".join(lines) + "\n\n"
