from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from app.collaboration.models import (
    ArtifactRef,
    CollaborationEvent,
    CollaborationRun,
    CollaborationTask,
    ResultPacket,
    RunStatus,
    TaskPacket,
    TaskStatus,
)
from app.runtime_paths import runtime_file


DB_PATH = runtime_file("data", "collaboration_runs.db")
_conn_local = threading.local()
_VALID_TASK_MODES = {"consult", "execute", "handoff"}


def _get_conn() -> sqlite3.Connection:
    conn = getattr(_conn_local, "conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collaboration_runs (
                run_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL,
                source_agent TEXT NOT NULL,
                target_agent TEXT NOT NULL,
                mode TEXT NOT NULL,
                goal TEXT DEFAULT '',
                project_path TEXT DEFAULT '',
                task_ids TEXT DEFAULT '[]',
                artifacts TEXT DEFAULT '[]',
                summary TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collaboration_tasks (
                task_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                owner TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL,
                packet TEXT NOT NULL,
                result TEXT DEFAULT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collaboration_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                task_id TEXT DEFAULT '',
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
            """
        )
        conn.commit()
        _conn_local.conn = conn
    return conn


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def _loads(data: str, fallback: Any) -> Any:
    try:
        return json.loads(data) if data else fallback
    except json.JSONDecodeError:
        return fallback


def create_run(
    *,
    session_id: str,
    goal: str,
    mode: str = "consult",
    project_path: str = "",
    source_agent: str = "personal",
    target_agent: str = "coding",
) -> CollaborationRun:
    if mode not in _VALID_TASK_MODES:
        raise ValueError(f"Invalid collaboration mode: {mode}")
    now = time.time()
    run = CollaborationRun(
        run_id=f"collab_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        goal=goal[:2000],
        mode=mode,  # type: ignore[arg-type]
        project_path=project_path,
        source_agent=source_agent,  # type: ignore[arg-type]
        target_agent=target_agent,  # type: ignore[arg-type]
        created_at=now,
        updated_at=now,
    )
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO collaboration_runs
        (run_id, session_id, status, source_agent, target_agent, mode, goal, project_path, task_ids, artifacts, summary, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run.run_id,
            run.session_id,
            run.status,
            run.source_agent,
            run.target_agent,
            run.mode,
            run.goal,
            run.project_path,
            _json(run.task_ids),
            _json([a.model_dump() for a in run.artifacts]),
            run.summary,
            run.created_at,
            run.updated_at,
        ),
    )
    conn.commit()
    record_event(run.run_id, "collaboration_run_created", run.model_dump())
    return run


def add_task(run_id: str, packet: TaskPacket) -> CollaborationTask:
    run = get_run(run_id)
    if run is None:
        raise ValueError(f"Collaboration run not found: {run_id}")
    now = time.time()
    task = CollaborationTask(
        task_id=f"ctask_{uuid.uuid4().hex[:12]}",
        run_id=run_id,
        owner=packet.owner,
        mode=packet.mode,
        status="pending",
        packet=packet,
        created_at=now,
        updated_at=now,
    )
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO collaboration_tasks
        (task_id, run_id, owner, mode, status, packet, result, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (
            task.task_id,
            task.run_id,
            task.owner,
            task.mode,
            task.status,
            task.packet.model_dump_json(),
            task.created_at,
            task.updated_at,
        ),
    )
    task_ids = list(run.task_ids)
    task_ids.append(task.task_id)
    conn.execute(
        "UPDATE collaboration_runs SET task_ids = ?, updated_at = ? WHERE run_id = ?",
        (_json(task_ids), now, run_id),
    )
    conn.commit()
    record_event(run_id, "collaboration_task_update", task.model_dump(), task.task_id)
    return task


def get_run(run_id: str) -> Optional[CollaborationRun]:
    row = _get_conn().execute("SELECT * FROM collaboration_runs WHERE run_id = ?", (run_id,)).fetchone()
    if not row:
        return None
    return CollaborationRun(
        run_id=row["run_id"],
        session_id=row["session_id"],
        status=row["status"],
        source_agent=row["source_agent"],
        target_agent=row["target_agent"],
        mode=row["mode"],
        goal=row["goal"],
        project_path=row["project_path"],
        task_ids=_loads(row["task_ids"], []),
        artifacts=[ArtifactRef.model_validate(a) for a in _loads(row["artifacts"], [])],
        summary=row["summary"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def get_task(task_id: str) -> Optional[CollaborationTask]:
    row = _get_conn().execute("SELECT * FROM collaboration_tasks WHERE task_id = ?", (task_id,)).fetchone()
    if not row:
        return None
    result = ResultPacket.model_validate_json(row["result"]) if row["result"] else None
    return CollaborationTask(
        task_id=row["task_id"],
        run_id=row["run_id"],
        owner=row["owner"],
        mode=row["mode"],
        status=row["status"],
        packet=TaskPacket.model_validate_json(row["packet"]),
        result=result,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def update_task(
    task_id: str,
    *,
    status: Optional[TaskStatus] = None,
    result: Optional[ResultPacket] = None,
    event_type: str = "collaboration_task_update",
) -> Optional[CollaborationTask]:
    task = get_task(task_id)
    if task is None:
        return None
    now = time.time()
    next_status = status or task.status
    next_result = result if result is not None else task.result
    conn = _get_conn()
    conn.execute(
        "UPDATE collaboration_tasks SET status = ?, result = ?, updated_at = ? WHERE task_id = ?",
        (
            next_status,
            next_result.model_dump_json() if next_result else None,
            now,
            task_id,
        ),
    )
    conn.commit()
    updated = get_task(task_id)
    if updated:
        record_event(updated.run_id, event_type, updated.model_dump(), task_id)
    return updated


def complete_run(
    run_id: str,
    status: RunStatus,
    summary: str = "",
    artifacts: Optional[List[ArtifactRef]] = None,
) -> Optional[CollaborationRun]:
    run = get_run(run_id)
    if run is None:
        return None
    now = time.time()
    merged_artifacts = artifacts if artifacts is not None else run.artifacts
    conn = _get_conn()
    conn.execute(
        """
        UPDATE collaboration_runs
        SET status = ?, summary = ?, artifacts = ?, updated_at = ?
        WHERE run_id = ?
        """,
        (
            status,
            summary[:4000],
            _json([a.model_dump() for a in merged_artifacts]),
            now,
            run_id,
        ),
    )
    conn.commit()
    updated = get_run(run_id)
    if updated:
        record_event(run_id, "collaboration_run_completed", updated.model_dump())
    return updated


def cancel_run(run_id: str) -> Optional[CollaborationRun]:
    run = get_run(run_id)
    if run is None:
        return None
    for task_id in run.task_ids:
        task = get_task(task_id)
        if task and task.status in {"pending", "running"}:
            update_task(task_id, status="cancelled")
    return complete_run(run_id, "cancelled", "Collaboration run cancelled")


def record_event(
    run_id: str,
    event_type: str,
    data: Dict[str, Any],
    task_id: str = "",
) -> CollaborationEvent:
    now = time.time()
    conn = _get_conn()
    cur = conn.execute(
        """
        INSERT INTO collaboration_events (run_id, task_id, type, data, timestamp)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, task_id, event_type, _json(data), now),
    )
    conn.commit()
    return CollaborationEvent(
        id=int(cur.lastrowid or 0),
        run_id=run_id,
        task_id=task_id,
        type=event_type,
        data=data,
        timestamp=now,
    )


def list_events(run_id: str) -> List[CollaborationEvent]:
    rows = _get_conn().execute(
        "SELECT * FROM collaboration_events WHERE run_id = ? ORDER BY id ASC",
        (run_id,),
    ).fetchall()
    return [
        CollaborationEvent(
            id=row["id"],
            run_id=row["run_id"],
            task_id=row["task_id"] or "",
            type=row["type"],
            data=_loads(row["data"], {}),
            timestamp=row["timestamp"],
        )
        for row in rows
    ]
