"""Persist structured plans as markdown files under runtime/plans/<session>/."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.runtime_paths import runtime_dir

from .models import PlanDraft, PlanTodo

_PLANS_ROOT_NAME = "plans"


def _plans_root() -> Path:
    return runtime_dir(_PLANS_ROOT_NAME)


def _session_dir(session_id: str) -> Path:
    d = _plans_root() / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\-_\s]", "", text.lower())
    s = re.sub(r"\s+", "-", s.strip())
    return s[:64] or "plan"


def _render_markdown(draft: PlanDraft, session_id: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    hr = "\n".join(f"- {a}" for a in draft.assumptions) if draft.assumptions else "- _none_"
    ac_lines = draft.acceptance_criteria or []

    # Steps section
    steps_text = "_no steps defined_"
    if draft.steps:
        steps_lines = []
        for s in draft.steps:
            deps = f" (depends: {', '.join(s.depends_on)})" if s.depends_on else ""
            pg = f" [{s.parallel_group}]" if s.parallel_group else ""
            details = f"\n  {s.details}" if s.details else ""
            steps_lines.append(f"1. **{s.title}**{deps}{pg}{details}")
        steps_text = "\n".join(steps_lines)

    # Todos section
    todos_text = "_no todos defined_"
    if draft.todos:
        todos_lines = []
        for t in draft.todos:
            deps = f" (depends: {', '.join(t.depends_on)})" if t.depends_on else ""
            ac = f"  → *AC*: {t.acceptance_criteria}" if t.acceptance_criteria else ""
            todos_lines.append(f"- [ ] **{t.title}**{deps}{ac}")
        todos_text = "\n".join(todos_lines)

    risks_text = "\n".join(f"- {r}" for r in draft.risks) if draft.risks else "- _none_"
    verify_text = "\n".join(f"- {v}" for v in ac_lines) if ac_lines else "- _see acceptance criteria_"

    return (
        f"# Plan: {draft.goal or 'Untitled Plan'}\n"
        f"\n"
        f"**Session**: `{session_id}` · **Created**: {now}\n"
        f"\n"
        f"---\n"
        f"\n"
        f"## Goal\n"
        f"{draft.goal or '_no goal set_'}\n"
        f"\n"
        f"## Assumptions\n"
        f"{hr}\n"
        f"\n"
        f"## Research Notes\n"
        f"_gathered during exploration_\n"
        f"\n"
        f"## Steps\n"
        f"{steps_text}\n"
        f"\n"
        f"## Todos\n"
        f"{todos_text}\n"
        f"\n"
        f"## Risks\n"
        f"{risks_text}\n"
        f"\n"
        f"## Verification\n"
        f"{verify_text}\n"
    )


def write_plan_file(
    session_id: str,
    draft: PlanDraft,
    raw_markdown: str = "",
) -> Path:
    """Render *draft* to markdown, persist to a timestamped file, and return the path."""
    md = raw_markdown if raw_markdown.strip() else _render_markdown(draft, session_id)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    slug = _slug(draft.goal or "plan")
    filename = f"{ts}-{slug}.md"
    out = _session_dir(session_id) / filename
    out.write_text(md, encoding="utf-8")
    return out


def read_plan_file(session_id: str, filename: str) -> str:
    """Return the contents of a specific plan markdown file."""
    path = _session_dir(session_id) / filename
    if not path.is_file():
        raise FileNotFoundError(f"Plan file not found: {path}")
    return path.read_text(encoding="utf-8")


@dataclass
class PlanFileMeta:
    filename: str
    path: str   # absolute path
    size_bytes: int
    created_at: str  # ISO 8601


def list_plan_files(session_id: str) -> list[PlanFileMeta]:
    """List all plan files for a session, newest first."""
    d = _session_dir(session_id)
    if not d.exists():
        return []
    results: list[PlanFileMeta] = []
    for p in sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            st = p.stat()
            results.append(PlanFileMeta(
                filename=p.name,
                path=str(p),
                size_bytes=st.st_size,
                created_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            ))
        except OSError:
            pass
    return results


def latest_plan_file(session_id: str) -> Optional[Path]:
    """Return the most recent plan file path, or None."""
    files = list_plan_files(session_id)
    if not files:
        return None
    return Path(files[0].path)
