"""Cross-session memory for Desktop Agent — persistent project-level memory store.

Stores memory entries as Markdown files in .agent-memory/ under the project root.
Each entry has YAML frontmatter with metadata (type, timestamp, tags).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

MEMORY_DIR_NAME = ".agent-memory"
MAX_MEMORY_FILES = 50
MAX_MEMORY_SIZE = 32 * 1024  # 32KB per file


@dataclass
class MemoryEntry:
    id: str
    type: str  # user_preference, project_knowledge, decision_log, reference
    content: str
    timestamp: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "content": self.content,
            "timestamp": self.timestamp,
            "tags": self.tags,
        }


def _memory_dir(project_path: str) -> Optional[Path]:
    if not project_path:
        return None
    d = Path(project_path) / MEMORY_DIR_NAME
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return d


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def save_memory(project_path: str, memory_type: str, content: str, tags: Optional[List[str]] = None) -> Optional[MemoryEntry]:
    """Persist a memory entry to the project's memory directory."""
    d = _memory_dir(project_path)
    if d is None:
        return None

    entry_id = f"{_slugify(content[:60])}-{int(time.time())}"
    entry = MemoryEntry(
        id=entry_id,
        type=memory_type,
        content=content,
        timestamp=time.time(),
        tags=tags or [],
    )

    filepath = d / f"{entry_id}.md"
    # Clean up if too many entries
    existing = sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime)
    while len(existing) >= MAX_MEMORY_FILES:
        try:
            existing[0].unlink()
            existing.pop(0)
        except OSError:
            break

    frontmatter = f"---\ntype: {memory_type}\ntimestamp: {entry.timestamp}\ntags: {json.dumps(entry.tags)}\n---\n\n"
    try:
        filepath.write_text(frontmatter + content, encoding="utf-8")
    except OSError:
        return None
    return entry


def load_memories(project_path: str) -> List[MemoryEntry]:
    """Load all memory entries for a project."""
    d = _memory_dir(project_path)
    if d is None:
        return []

    entries: List[MemoryEntry] = []
    for f in sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            content = f.read_text(encoding="utf-8")
        except OSError:
            continue

        # Parse YAML frontmatter
        fm_match = re.match(r"^---\n(.*?)\n---\n\n(.*)", content, re.DOTALL)
        if fm_match:
            body = fm_match.group(2)
            try:
                meta = {}
                for line in fm_match.group(1).split("\n"):
                    if ":" in line:
                        key, _, val = line.partition(":")
                        meta[key.strip()] = val.strip()
            except Exception:
                meta = {}
        else:
            body = content
            meta = {}

        entries.append(MemoryEntry(
            id=f.stem,
            type=meta.get("type", "unknown"),
            content=body.strip(),
            timestamp=float(meta.get("timestamp", f.stat().st_mtime)),
            tags=json.loads(meta.get("tags", "[]")),
        ))

    return entries


def delete_memory(project_path: str, memory_id: str) -> bool:
    """Delete a memory entry by id."""
    d = _memory_dir(project_path)
    if d is None:
        return False
    fp = d / f"{memory_id}.md"
    try:
        if fp.exists():
            fp.unlink()
            return True
    except OSError:
        pass
    return False


def search_memories(project_path: str, query: str) -> List[MemoryEntry]:
    """Simple keyword search across memory content."""
    entries = load_memories(project_path)
    query_lower = query.lower()
    return [
        e for e in entries
        if query_lower in e.content.lower() or any(query_lower in t.lower() for t in e.tags)
    ]


def build_memory_prompt(project_path: str, max_entries: int = 5) -> str:
    """Build a memory context string for injection into the system prompt."""
    entries = load_memories(project_path)
    if not entries:
        return ""

    # Show most recent entries, prioritized by type
    priority_order = {"user_preference": 0, "project_knowledge": 1, "decision_log": 2, "reference": 3}
    entries.sort(key=lambda e: (priority_order.get(e.type, 99), -e.timestamp))

    selected = entries[:max_entries]
    parts = ["## Session Memory (.agent-memory/)\n"]
    for e in selected:
        type_label = {
            "user_preference": "偏好",
            "project_knowledge": "知识",
            "decision_log": "决策",
            "reference": "参考",
        }.get(e.type, e.type)
        parts.append(f"- [{type_label}] {e.content[:300]}")
    return "\n".join(parts) + "\n"
