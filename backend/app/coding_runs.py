"""Run journal and Git worktree helpers for coding-agent runs."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from contextvars import ContextVar, Token
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import load_config
from app.project_manager import ProjectManager
from app.runtime_paths import runtime_dir, runtime_file
from app.security import redact_sensitive_text


DB_PATH = runtime_file("data", "coding_runs.db")
_current_run: ContextVar[Optional["RunContext"]] = ContextVar("coding_run_context", default=None)


@dataclass
class RunContext:
    run_id: str
    session_id: str
    project_path: str
    mode: str
    worktree_path: str = ""
    base_branch: str = ""
    base_commit: str = ""
    prompt: str = ""

    @property
    def active_path(self) -> str:
        return self.worktree_path or self.project_path


_conn_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    conn = getattr(_conn_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                project_path TEXT NOT NULL,
                mode TEXT NOT NULL,
                worktree_path TEXT DEFAULT '',
                base_branch TEXT DEFAULT '',
                base_commit TEXT DEFAULT '',
                prompt TEXT DEFAULT '',
                status TEXT DEFAULT 'running',
                summary TEXT DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
            """
        )
        conn.commit()
        _conn_local.conn = conn
    return conn


def set_run_context(ctx: Optional[RunContext]) -> Token:
    return _current_run.set(ctx)


def reset_run_context(token: Token) -> None:
    _current_run.reset(token)


def get_run_context() -> Optional[RunContext]:
    return _current_run.get()


def _run_git(args: List[str], cwd: str, timeout: int = 30, input_text: Optional[str] = None) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, redact_sensitive_text(result.stdout), redact_sensitive_text(result.stderr)
    except subprocess.TimeoutExpired:
        return 1, "", f"git command timed out after {timeout}s"
    except OSError as exc:
        return 1, "", str(exc)


def _git_info(project_path: str) -> Dict[str, str]:
    code, root, _ = _run_git(["rev-parse", "--show-toplevel"], project_path)
    if code != 0:
        return {}
    code, branch, _ = _run_git(["branch", "--show-current"], project_path)
    code2, commit, _ = _run_git(["rev-parse", "HEAD"], project_path)
    return {
        "root": root.strip(),
        "branch": branch.strip() if code == 0 else "",
        "commit": commit.strip() if code2 == 0 else "",
    }


def _project_id(project_path: str) -> str:
    digest = hashlib.sha1(project_path.encode("utf-8")).hexdigest()[:12]
    return digest


def _insert_run(ctx: RunContext, status: str = "running") -> None:
    now = time.time()
    conn = _get_conn()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO runs
            (run_id, session_id, project_path, mode, worktree_path, base_branch, base_commit, prompt, status, updated_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM runs WHERE run_id = ?), ?))
            """,
            (
                ctx.run_id,
                ctx.session_id,
                ctx.project_path,
                ctx.mode,
                ctx.worktree_path,
                ctx.base_branch,
                ctx.base_commit,
                ctx.prompt,
                status,
                now,
                ctx.run_id,
                now,
            ),
        )
        conn.commit()
    finally:
        pass



def create_coding_run(session_id: str, run_id: str, prompt: str = "") -> Optional[RunContext]:
    cfg = load_config()
    coding_cfg = getattr(cfg, "coding_agent", None)
    if coding_cfg is not None and not getattr(coding_cfg, "enabled", True):
        return None

    project = ProjectManager.get_current()
    if not project:
        return None

    project_path = str(Path(project["path"]).resolve())
    git_info = _git_info(project_path)
    default_mode = getattr(coding_cfg, "default_execution_mode", "worktree") if coding_cfg else "worktree"
    mode = "current_dir"
    worktree_path = ""
    base_branch = git_info.get("branch", "")
    base_commit = git_info.get("commit", "")

    if git_info and default_mode == "worktree" and base_commit:
        root = git_info.get("root") or project_path
        target = runtime_dir("worktrees") / _project_id(root) / run_id
        target.parent.mkdir(parents=True, exist_ok=True)
        code, _, stderr = _run_git(["worktree", "add", "--detach", str(target), base_commit], root, timeout=60)
        if code == 0:
            mode = "worktree"
            worktree_path = str(target.resolve())
        else:
            record_event(run_id, "guardrail_decision", {
                "risk": "medium",
                "decision": "fallback",
                "reason": f"Git worktree creation failed, using current directory: {stderr}",
                "requires_approval": False,
            })

    ctx = RunContext(
        run_id=run_id,
        session_id=session_id,
        project_path=project_path,
        mode=mode,
        worktree_path=worktree_path,
        base_branch=base_branch,
        base_commit=base_commit,
        prompt=prompt[:2000],
    )
    _insert_run(ctx)
    record_event(run_id, "run_created", asdict(ctx))
    return ctx


def record_event(run_id: str, event_type: str, data: Dict[str, Any]) -> None:
    if not run_id:
        return
    conn = _get_conn()
    now = time.time()
    try:
        conn.execute(
            "INSERT INTO run_events (run_id, type, data, timestamp) VALUES (?, ?, ?, ?)",
            (run_id, event_type, json.dumps(data, ensure_ascii=False), now),
        )
        conn.execute("UPDATE runs SET updated_at = ? WHERE run_id = ?", (now, run_id))
        conn.commit()
    finally:
        pass



def complete_run(
    run_id: str,
    status: str,
    summary: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> None:
    if not run_id:
        return
    conn = _get_conn()
    now = time.time()
    try:
        conn.execute(
            "UPDATE runs SET status = ?, summary = ?, updated_at = ? WHERE run_id = ?",
            (status, summary[:4000], now, run_id),
        )
        conn.commit()
    finally:
        pass

    payload: Dict[str, Any] = {"run_id": run_id, "status": status, "summary": summary}
    if details:
        payload.update(details)
    record_event(run_id, "run_completed", payload)


def list_runs(limit: int = 100) -> List[Dict[str, Any]]:
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM runs ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        pass



def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    try:
        run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if not run:
            return None
        events = conn.execute(
            "SELECT type, data, timestamp FROM run_events WHERE run_id = ? ORDER BY id ASC",
            (run_id,),
        ).fetchall()
        return {
            "run": dict(run),
            "events": [
                {"type": row["type"], "data": json.loads(row["data"]), "timestamp": row["timestamp"]}
                for row in events
            ],
        }
    finally:
        pass



def discard_run(run_id: str) -> Dict[str, Any]:
    data = get_run(run_id)
    if not data:
        return {"error": "Run not found"}
    run = data["run"]
    worktree = run.get("worktree_path") or ""
    project = run.get("project_path") or ""
    if worktree and Path(worktree).exists():
        code, _, stderr = _run_git(["worktree", "remove", "--force", worktree], project, timeout=60)
        if code != 0:
            try:
                shutil.rmtree(worktree)
            except OSError as exc:
                return {"error": f"Failed to remove worktree: {stderr or exc}"}
    complete_run(run_id, "discarded", "Worktree discarded")
    return {"status": "discarded", "run_id": run_id}


def worktree_status(run_id: str) -> Dict[str, Any]:
    data = get_run(run_id)
    if not data:
        return {"error": "Run not found"}
    run = data["run"]
    cwd = run.get("worktree_path") or run.get("project_path")
    if not cwd:
        return {"error": "Run has no project path"}
    code, status, stderr = _run_git(["status", "--short"], cwd)
    if code != 0:
        return {"error": stderr}
    code, diff, stderr = _run_git(["diff", "--stat"], cwd)
    return {
        "run_id": run_id,
        "mode": run.get("mode"),
        "worktree_path": run.get("worktree_path"),
        "status": status,
        "diff_stat": diff if code == 0 else stderr,
    }


def apply_run(run_id: str) -> Dict[str, Any]:
    data = get_run(run_id)
    if not data:
        return {"error": "Run not found"}
    run = data["run"]
    worktree = run.get("worktree_path") or ""
    project = run.get("project_path") or ""
    base_commit = run.get("base_commit") or "HEAD"
    if not worktree:
        return {"error": "Run was not executed in a worktree"}
    _run_git(["add", "-N", "."], worktree, timeout=60)
    code, diff, stderr = _run_git(["diff", "--binary", base_commit], worktree, timeout=60)
    if code != 0:
        return {"error": f"Failed to compute diff: {stderr}"}
    if not diff.strip():
        return {"status": "no_changes", "run_id": run_id}
    code, stdout, stderr = _run_git(["apply", "--whitespace=nowarn", "-"], project, timeout=60, input_text=diff)
    if code != 0:
        return {"error": f"Failed to apply diff: {stderr}"}
    complete_run(run_id, "applied", "Diff applied to current project")
    return {"status": "applied", "run_id": run_id, "output": stdout}


def merge_run(run_id: str, branch_name: Optional[str] = None) -> Dict[str, Any]:
    data = get_run(run_id)
    if not data:
        return {"error": "Run not found"}
    run = data["run"]
    worktree = run.get("worktree_path") or ""
    project = run.get("project_path") or ""
    if not worktree:
        return {"error": "Run was not executed in a worktree"}
    branch = branch_name or f"desktop-agent/{run_id}"
    code, _, stderr = _run_git(["checkout", "-B", branch], worktree)
    if code != 0:
        return {"error": f"Failed to create worktree branch: {stderr}"}
    _run_git(["add", "-A"], worktree)
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "Desktop Agent")
    env.setdefault("GIT_AUTHOR_EMAIL", "desktop-agent@example.local")
    env.setdefault("GIT_COMMITTER_NAME", "Desktop Agent")
    env.setdefault("GIT_COMMITTER_EMAIL", "desktop-agent@example.local")
    try:
        commit = subprocess.run(
            ["git", "commit", "--no-gpg-sign", "-m", f"Desktop Agent run {run_id}"],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": f"Failed to commit worktree changes: {exc}"}
    if commit.returncode not in (0, 1):
        return {"error": f"Failed to commit worktree changes: {redact_sensitive_text(commit.stderr)}"}
    code, commit_hash, stderr = _run_git(["rev-parse", "HEAD"], worktree)
    if code != 0:
        return {"error": f"Failed to read worktree commit: {stderr}"}
    code, _, stderr = _run_git(["branch", "-f", branch, commit_hash.strip()], project)
    if code != 0:
        return {"error": f"Failed to create local branch in project: {stderr}"}
    code, stdout, stderr = _run_git(["merge", "--no-ff", branch], project, timeout=60)
    if code != 0:
        return {"error": f"Failed to merge branch: {stderr}"}
    complete_run(run_id, "merged", f"Merged {branch}")
    return {"status": "merged", "run_id": run_id, "branch": branch, "output": stdout}
