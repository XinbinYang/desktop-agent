"""SharedBlackboard — run-scoped key/value store for Personal ↔ Coding Agent coordination.

Backed by the same SQLite database as collaboration_runs, in a separate table.
Supports visibility filtering: "both" (default) or "coding_only".
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from typing import Any, List, Optional

from app.runtime_paths import runtime_file

DB_PATH = runtime_file("data", "collaboration_runs.db")
_conn_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    conn = getattr(_conn_local, "bb_conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collab_blackboard (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT NOT NULL,
                key         TEXT NOT NULL,
                value       TEXT NOT NULL,
                author      TEXT NOT NULL,
                visibility  TEXT NOT NULL DEFAULT 'both',
                ts          REAL NOT NULL,
                UNIQUE(run_id, key) ON CONFLICT REPLACE
            )
            """
        )
        conn.commit()
        _conn_local.bb_conn = conn
    return conn


def bb_put(
    run_id: str,
    key: str,
    value: Any,
    author: str,
    visibility: str = "both",
) -> None:
    """Write (or overwrite) a key in the blackboard for a given run."""
    _get_conn().execute(
        """
        INSERT INTO collab_blackboard (run_id, key, value, author, visibility, ts)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, key) DO UPDATE SET
            value = excluded.value,
            author = excluded.author,
            visibility = excluded.visibility,
            ts = excluded.ts
        """,
        (run_id, key, json.dumps(value, ensure_ascii=False), author, visibility, time.time()),
    )
    _get_conn().commit()


def bb_get(run_id: str, key: str) -> Optional[dict]:
    """Return a single blackboard entry as a dict, or None if missing."""
    row = _get_conn().execute(
        "SELECT * FROM collab_blackboard WHERE run_id = ? AND key = ?",
        (run_id, key),
    ).fetchone()
    if row is None:
        return None
    return {
        "run_id": row["run_id"],
        "key": row["key"],
        "value": json.loads(row["value"]),
        "author": row["author"],
        "visibility": row["visibility"],
        "ts": row["ts"],
    }


def bb_list(run_id: str, visibility_filter: str = "both") -> List[dict]:
    """Return all blackboard entries for a run, optionally filtered by visibility.

    visibility_filter="both" returns everything.
    visibility_filter="coding_only" returns only entries where visibility="coding_only".
    """
    if visibility_filter == "both":
        rows = _get_conn().execute(
            "SELECT * FROM collab_blackboard WHERE run_id = ? ORDER BY ts ASC",
            (run_id,),
        ).fetchall()
    else:
        rows = _get_conn().execute(
            "SELECT * FROM collab_blackboard WHERE run_id = ? AND visibility = ? ORDER BY ts ASC",
            (run_id, visibility_filter),
        ).fetchall()
    return [
        {
            "run_id": row["run_id"],
            "key": row["key"],
            "value": json.loads(row["value"]),
            "author": row["author"],
            "visibility": row["visibility"],
            "ts": row["ts"],
        }
        for row in rows
    ]


def bb_delete(run_id: str, key: str) -> None:
    """Remove a single key from the blackboard."""
    _get_conn().execute(
        "DELETE FROM collab_blackboard WHERE run_id = ? AND key = ?",
        (run_id, key),
    )
    _get_conn().commit()
