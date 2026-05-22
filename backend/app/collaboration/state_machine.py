"""CollaborationStateMachine — explicit state machine for Personal ↔ Coding collaboration.

Tracks phase transitions in SQLite (same DB as collaboration_runs) and validates
every transition against a hard-coded transition table. Supports pause/resume.

Phases:
  pending → analyzing → planning → awaiting_user → executing → verifying → critiquing → completed
                          ↓             ↓              ↓            ↓
                       executing    paused          paused      failed
                           ↓          ↓
                        paused     executing
                          ↓
                       failed
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Dict, List, Optional

from app.runtime_paths import runtime_file

DB_PATH = runtime_file("data", "collaboration_runs.db")
_conn_local = threading.local()

# Type alias
CollabPhase = str  # Literal constrained by _VALID_TRANSITIONS keys + values

_VALID_TRANSITIONS: Dict[str, List[str]] = {
    "pending": ["analyzing"],
    "analyzing": ["planning", "executing", "failed"],
    "planning": ["awaiting_user", "executing"],
    "awaiting_user": ["executing", "paused", "failed"],
    "executing": ["awaiting_user", "verifying", "critiquing", "paused", "failed"],
    "verifying": ["critiquing", "completed", "failed"],
    "critiquing": ["completed", "failed"],
    "paused": ["executing", "failed"],
    "completed": [],
    "failed": [],
}


def _get_conn() -> sqlite3.Connection:
    conn = getattr(_conn_local, "sm_conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collab_run_phases (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id    TEXT NOT NULL,
                phase     TEXT NOT NULL,
                ts        REAL NOT NULL,
                note      TEXT DEFAULT ''
            )
            """
        )
        conn.commit()
        _conn_local.sm_conn = conn
    return conn


def _get_current_phase(run_id: str) -> Optional[str]:
    row = _get_conn().execute(
        "SELECT phase FROM collab_run_phases WHERE run_id = ? ORDER BY id DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    return row["phase"] if row else None


class CollaborationStateMachine:
    """Explicit state machine for a collaboration run.

    Usage::

        sm = CollaborationStateMachine("collab_abc123")
        sm.transition("analyzing")
        sm.transition("executing")
        # ...
        assert sm.phase() == "executing"
        if sm.can_pause():
            sm.transition("paused")
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._run_id = run_id

    def phase(self) -> CollabPhase:
        """Return the current phase. Defaults to 'pending' if no history."""
        return _get_current_phase(self._run_id) or "pending"

    def transition(self, new_phase: CollabPhase, note: str = "") -> None:
        """Transition to *new_phase*, validating legality.

        Raises ValueError if the transition is not allowed.
        """
        current = self.phase()
        allowed = _VALID_TRANSITIONS.get(current, [])
        if new_phase not in allowed:
            raise ValueError(
                f"Invalid transition: {current} → {new_phase}. "
                f"Allowed transitions from '{current}': {allowed}"
            )
        conn = _get_conn()
        conn.execute(
            "INSERT INTO collab_run_phases (run_id, phase, ts, note) VALUES (?, ?, ?, ?)",
            (self._run_id, new_phase, time.time(), note),
        )
        conn.commit()

    def can_pause(self) -> bool:
        """Return True if pausing is legal from the current phase."""
        return "paused" in _VALID_TRANSITIONS.get(self.phase(), [])

    def resume(self) -> None:
        """Resume from paused by transitioning back to the pre-pause phase.

        Heuristic: walk back through the phase history to find the phase
        immediately before 'paused', then transition to 'executing'.
        """
        if self.phase() != "paused":
            raise ValueError(f"Cannot resume from phase '{self.phase()}' — must be 'paused'.")
        # Find the phase that was active before we paused
        rows = _get_conn().execute(
            "SELECT phase FROM collab_run_phases WHERE run_id = ? ORDER BY id DESC LIMIT 3",
            (self._run_id,),
        ).fetchall()
        pre_pause = "executing"  # safe default
        for row in rows:
            if row["phase"] != "paused":
                pre_pause = row["phase"]
                break
        if pre_pause not in _VALID_TRANSITIONS.get("paused", []):
            pre_pause = "executing"
        self.transition(pre_pause, note="resumed from pause")


def list_phase_history(run_id: str) -> List[Dict]:
    """Return all phase transitions for a run, ordered by time."""
    rows = _get_conn().execute(
        "SELECT phase, ts, note FROM collab_run_phases WHERE run_id = ? ORDER BY id ASC",
        (run_id,),
    ).fetchall()
    return [{"phase": r["phase"], "ts": r["ts"], "note": r["note"]} for r in rows]
