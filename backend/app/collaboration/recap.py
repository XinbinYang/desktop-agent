"""RunRecap — compact summary of a collaboration run for Personal Agent context.

Converts a raw event stream (50+ events) into a ≤2 KB recap so Personal Agent
messages history stays manageable.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.collaboration.models import EvidenceEntry

# Keywords that indicate a decision was made
_DECISION_KEYWORDS = re.compile(
    r"(决定|选择|方案|策略|conclusion|decided|chose|approach|strategy|plan|因此|所以|therefore)",
    re.IGNORECASE,
)

# Tool names that write files
_FILE_WRITE_TOOLS = frozenset({
    "file_write", "file_edit", "file_create", "write_file", "edit_file",
    "apply_diff", "patch_file",
})


class RunRecap(BaseModel):
    run_id: str
    one_liner: str
    key_decisions: List[str]
    changed_files: List[str]
    evidence_ledger: List[EvidenceEntry]
    failure_summary: Optional[str]
    trace_anchor: str  # == run_id; frontend uses this to expand full event log


def recap_run(run_id: str) -> RunRecap:
    """Build a RunRecap from stored collaboration events (≤ 2 KB text budget)."""
    from app.collaboration.executor import _extract_evidence
    from app.collaboration.manager import list_events

    raw_events = list_events(run_id)
    events: List[Dict[str, Any]] = [e.model_dump() for e in raw_events]
    return recap_from_events(run_id, events)


def recap_from_events(run_id: str, events: List[Dict[str, Any]]) -> RunRecap:
    """Build a RunRecap from an in-memory event list (testable without DB)."""
    from app.collaboration.executor import _extract_evidence

    changed_files: List[str] = []
    key_decisions: List[str] = []
    failure_summary: Optional[str] = None
    one_liner = ""

    for event in events:
        etype = event.get("type", "")
        data = event.get("data") or {}

        # Extract changed files from file-write tool calls
        if etype == "tool_call":
            tool_name = data.get("name") or ""
            if tool_name in _FILE_WRITE_TOOLS:
                args = data.get("args") or {}
                path = (
                    args.get("path")
                    or args.get("file_path")
                    or args.get("filename")
                    or ""
                )
                if path and path not in changed_files:
                    changed_files.append(path)

        # Extract decision sentences from content events
        elif etype == "content":
            text = data.get("text") or ""
            for sentence in re.split(r"[。.!！\n]", text):
                sentence = sentence.strip()
                if sentence and _DECISION_KEYWORDS.search(sentence) and len(sentence) <= 200:
                    key_decisions.append(sentence[:200])
                    if len(key_decisions) >= 5:
                        break

        # Extract failure info from run_completed
        elif etype == "run_completed":
            if data.get("status") in ("failed", "cancelled"):
                failure_summary = (data.get("summary") or "")[:300]
            if not one_liner:
                one_liner = (data.get("summary") or "")[:100]

        # Grab one-liner from collaboration_run_created if available
        elif etype == "collaboration_run_created":
            if not one_liner:
                goal = data.get("goal") or ""
                one_liner = goal[:100]

    # Fallback one-liner
    if not one_liner and events:
        for event in events:
            goal = (event.get("data") or {}).get("goal") or ""
            if goal:
                one_liner = goal[:100]
                break

    evidence = _extract_evidence(events)

    return RunRecap(
        run_id=run_id,
        one_liner=one_liner,
        key_decisions=key_decisions[:5],
        changed_files=changed_files[:20],
        evidence_ledger=evidence,
        failure_summary=failure_summary,
        trace_anchor=run_id,
    )
