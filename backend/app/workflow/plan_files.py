"""Persist structured plans as markdown files under runtime/plans/<session>/."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.runtime_paths import runtime_dir

from .models import PlanDraft

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


def _render_markdown(draft: PlanDraft, session_id: str, research_notes: str = "") -> str:
    """Render a plan as the four-block Claude-Code-style template:
    任务目标 / 任务方案 (PART 1..N) / 关键文件清单 / 验证.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # ── 任务目标 / Goal: why + outcome, with assumptions/risks/research as light sub-notes ──
    goal_block = (draft.context.strip() or draft.goal.strip() or "_no goal set_")
    note_lines: list[str] = []
    for a in draft.assumptions:
        note_lines.append(f"> 假设 / Assumption: {a}")
    for r in draft.risks:
        note_lines.append(f"> 风险 / Risk: {r}")
    rn = research_notes.strip()
    if rn:
        note_lines.append(f"> 调研 / Research: {rn}")
    goal_section = goal_block + ("\n\n" + "\n".join(note_lines) if note_lines else "")

    # ── 任务方案 / Approach: each todo (or step) is a numbered PART ──
    part_lines: list[str] = []
    if draft.todos:
        for i, todo in enumerate(draft.todos, 1):
            deps = f" (depends: {', '.join(todo.depends_on)})" if todo.depends_on else ""
            group = f" [{todo.parallel_group}]" if todo.parallel_group else ""
            part_lines.append(f"### PART {i} — {todo.title}{deps}{group}")
            if todo.acceptance_criteria:
                part_lines.append(f"- 验收 / Acceptance: {todo.acceptance_criteria}")
            part_lines.append("")
    elif draft.steps:
        for i, step in enumerate(draft.steps, 1):
            deps = f" (depends: {', '.join(step.depends_on)})" if step.depends_on else ""
            group = f" [{step.parallel_group}]" if step.parallel_group else ""
            part_lines.append(f"### PART {i} — {step.title}{deps}{group}")
            if step.details:
                part_lines.append(f"- {step.details}")
            part_lines.append("")
    approach_section = "\n".join(part_lines).strip() or "_no tasks defined_"

    # ── 关键文件清单 / Critical Files ──
    if draft.critical_files:
        cf_lines = ["| 文件 / File | 改动 / Change |", "|---|---|"]
        for cf in draft.critical_files:
            path = str(cf.get("path", "")).strip()
            if not path:
                continue
            change = str(cf.get("change", "")).strip() or "—"
            cf_lines.append(f"| `{path}` | {change} |")
        critical_section = "\n".join(cf_lines) if len(cf_lines) > 2 else "_探索阶段确认 / determined during exploration_"
    else:
        critical_section = "_探索阶段确认 / determined during exploration_"

    # ── 验证 / Verification ──
    verification = (
        "\n".join(f"- {v}" for v in draft.acceptance_criteria)
        if draft.acceptance_criteria
        else "- _见各 PART 的验收标准 / see each PART's acceptance criteria_"
    )

    return (
        f"# {draft.goal or 'Untitled Plan'}\n"
        "\n"
        f"**Session**: `{session_id}` | **Created**: {now}\n"
        "\n"
        "---\n"
        "\n"
        "## 任务目标 / Goal\n"
        f"{goal_section}\n"
        "\n"
        "## 任务方案 / Approach\n"
        f"{approach_section}\n"
        "\n"
        "## 关键文件清单 / Critical Files\n"
        f"{critical_section}\n"
        "\n"
        "## 验证 / Verification\n"
        f"{verification}\n"
    )


def write_plan_file(
    session_id: str,
    draft: PlanDraft,
    raw_markdown: str = "",
    research_notes: str = "",
) -> Path:
    """Render *draft* to markdown, persist to a timestamped file, and return the path."""
    del raw_markdown  # Kept for API compatibility; user-visible plans are task-first.
    md = _render_markdown(draft, session_id, research_notes=research_notes)
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
    path: str
    size_bytes: int
    created_at: str


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
