"""Agent Eval Runner — execute coding tasks in isolated worktrees and measure results."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from app.coding_runs import (
    RunContext,
    complete_run,
    create_coding_run,
    discard_run,
    get_run,
    record_event,
)

logger = logging.getLogger(__name__)

# ── data types ──────────────────────────────────────────────────────────────

@dataclass
class EvalTask:
    id: str
    category: str
    prompt: str
    verification: str

    @classmethod
    def from_manifest(cls, data: Dict[str, Any]) -> EvalTask:
        return cls(
            id=data.get("id", ""),
            category=data.get("category", ""),
            prompt=data.get("prompt", ""),
            verification=data.get("verification", ""),
        )


@dataclass
class EvalResult:
    task_id: str
    passed: bool
    iterations: int = 0
    tool_calls: int = 0
    duration_ms: int = 0
    files_changed: List[str] = field(default_factory=list)
    verification_output: str = ""
    verification_exit_code: int = -1
    run_id: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "passed": self.passed,
            "iterations": self.iterations,
            "tool_calls": self.tool_calls,
            "duration_ms": self.duration_ms,
            "files_changed": self.files_changed,
            "verification_output": self.verification_output[:2000],
            "verification_exit_code": self.verification_exit_code,
            "run_id": self.run_id,
            "error": self.error,
        }


@dataclass
class EvalRun:
    run_id: str
    status: str = "idle"  # idle, running, completed, failed
    results: List[EvalResult] = field(default_factory=list)
    started_at: float = 0
    completed_at: float = 0
    total_tasks: int = 0
    completed_tasks: int = 0

    @property
    def success_rate(self) -> Optional[float]:
        if not self.results:
            return None
        passed = sum(1 for r in self.results if r.passed)
        return passed / len(self.results)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "total_tasks": self.total_tasks,
            "completed_tasks": self.completed_tasks,
            "success_rate": self.success_rate,
            "results": [r.to_dict() for r in self.results],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


# ── manifest loader ─────────────────────────────────────────────────────────

def load_manifest() -> Tuple[List[EvalTask], Optional[str]]:
    """Load eval tasks from agent_evals/manifest.json.

    Returns (tasks, error_message). error_message is None on success.
    """
    root = Path(__file__).resolve().parents[2]  # backend -> repo root
    manifest_path = root / "agent_evals" / "manifest.json"

    if not manifest_path.exists():
        return [], f"Manifest not found: {manifest_path}"

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return [], str(e)

    tasks = [EvalTask.from_manifest(t) for t in data.get("tasks", [])]
    return tasks, None


# ── single task executor ────────────────────────────────────────────────────

async def _execute_single_task(
    task: EvalTask,
    project_path: str,
    timeout_seconds: int = 300,
) -> EvalResult:
    """Execute one eval task in an isolated worktree.

    Flow:
      1. Create worktree via coding_runs.create_coding_run
      2. Run AgentSession with task.prompt (non-streaming)
      3. Record tool calls and iterations
      4. Execute task.verification command
      5. Record pass/fail
      6. Discard worktree
    """
    result = EvalResult(task_id=task.id, passed=False)
    started = time.time()
    ctx: Optional[RunContext] = None

    try:
        # 1. Create worktree
        session_id = f"eval_{task.id}_{int(started)}"
        ctx = await asyncio.to_thread(
            create_coding_run,
            project_path=project_path,
            session_id=session_id,
            mode="worktree",
            prompt=task.prompt,
        )
        if ctx is None:
            result.error = "Failed to create coding run worktree"
            return result

        result.run_id = ctx.run_id

        # 2. Run agent
        from app.agent import AgentSession
        from app.agents.manager import AgentManager
        from app.config import get_model_for_agent

        model_id = get_model_for_agent("coding")

        session = AgentSession(
            model_id=model_id,
            session_id=session_id,
            role_id=AgentManager.get_default_role("coding"),
            agent_type="coding",
        )
        session.max_iterations = 30  # Limit iterations for eval

        try:
            iteration_count = 0
            tool_call_count = 0
            files_seen: set = set()

            async for event in session.run(task.prompt):
                event_type = event.get("type", "")
                if event_type == "tool_call":
                    tool_call_count += 1
                    data = event.get("data", {})
                    tool_name = data.get("name", "")
                    tool_args = data.get("args", {})
                    # Track file changes
                    path = tool_args.get("path") or tool_args.get("file_path") or ""
                    if path and tool_name in ("file_write", "file_patch", "file_delete"):
                        files_seen.add(path)
                elif event_type == "status":
                    iteration_count += 1

            result.iterations = iteration_count
            result.tool_calls = tool_call_count
            result.files_changed = list(files_seen)

        except Exception as e:
            result.error = f"Agent execution failed: {e}"

        # 3. Verification
        if task.verification:
            try:
                proc = await asyncio.create_subprocess_shell(
                    task.verification,
                    cwd=project_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=60
                )
                result.verification_exit_code = proc.returncode or 0
                result.verification_output = (
                    (stdout or b"").decode("utf-8", errors="replace") +
                    (stderr or b"").decode("utf-8", errors="replace")
                )
                result.passed = result.verification_exit_code == 0
            except asyncio.TimeoutError:
                result.verification_output = "Verification timed out (60s)"
                result.passed = False

    except Exception as e:
        result.error = str(e)
    finally:
        # 4. Cleanup worktree
        if ctx:
            try:
                await asyncio.to_thread(discard_run, ctx.run_id)
            except Exception as e:
                logger.warning("Failed to discard eval worktree: %s", e)

    result.duration_ms = int((time.time() - started) * 1000)
    return result


# ── batch runner ────────────────────────────────────────────────────────────

class EvalRunner:
    """Orchestrates batch eval execution."""

    def __init__(self):
        self._current_run: Optional[EvalRun] = None
        self._history: List[EvalRun] = []  # Last 10 runs

    @property
    def current_run(self) -> Optional[EvalRun]:
        return self._current_run

    def get_history(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._history]

    async def run_all(
        self,
        project_path: str,
        task_ids: Optional[List[str]] = None,
        max_concurrent: int = 2,
        progress_callback: Optional[callable] = None,
    ) -> EvalRun:
        """Run all (or selected) eval tasks."""
        tasks, err = load_manifest()
        if err:
            run = EvalRun(run_id=str(uuid.uuid4())[:8], status="failed")
            logger.error("Failed to load manifest: %s", err)
            return run

        if task_ids:
            tasks = [t for t in tasks if t.id in task_ids]

        run = EvalRun(
            run_id=str(uuid.uuid4())[:8],
            status="running",
            total_tasks=len(tasks),
            started_at=time.time(),
        )
        self._current_run = run

        # Execute tasks with concurrency limit
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _run_one(task: EvalTask) -> EvalResult:
            async with semaphore:
                result = await _execute_single_task(task, project_path)
                run.completed_tasks += 1
                run.results.append(result)
                if progress_callback:
                    try:
                        progress_callback(run.to_dict())
                    except Exception:
                        pass
                return result

        try:
            await asyncio.gather(
                *[_run_one(t) for t in tasks],
                return_exceptions=True,
            )
            run.status = "completed"
        except Exception as e:
            run.status = "failed"
            logger.error("Eval run failed: %s", e)

        run.completed_at = time.time()

        # Keep history (max 10)
        self._history.append(run)
        if len(self._history) > 10:
            self._history = self._history[-10:]

        return run

    def compare_runs(self, run1_id: str, run2_id: str) -> Optional[Dict[str, Any]]:
        """Compare two eval runs and identify regressions/improvements."""
        r1 = next((r for r in self._history if r.run_id == run1_id), None)
        r2 = next((r for r in self._history if r.run_id == run2_id), None)
        if not r1 or not r2:
            return None

        comparisons = []
        for t1 in r1.results:
            t2 = next((r for r in r2.results if r.task_id == t1.task_id), None)
            if not t2:
                comparisons.append({
                    "task_id": t1.task_id,
                    "change": "removed",
                    "before": t1.to_dict(),
                })
                continue

            change = "same"
            if t1.passed and not t2.passed:
                change = "regression"
            elif not t1.passed and t2.passed:
                change = "improvement"
            elif t1.iterations != t2.iterations:
                change = "changed"

            comparisons.append({
                "task_id": t1.task_id,
                "change": change,
                "before": {"passed": t1.passed, "iterations": t1.iterations, "duration_ms": t1.duration_ms},
                "after": {"passed": t2.passed, "iterations": t2.iterations, "duration_ms": t2.duration_ms},
            })

        return {
            "run1": {"id": r1.run_id, "success_rate": r1.success_rate},
            "run2": {"id": r2.run_id, "success_rate": r2.success_rate},
            "comparisons": comparisons,
        }


# ── singleton ───────────────────────────────────────────────────────────────

_runner: Optional[EvalRunner] = None


def get_eval_runner() -> EvalRunner:
    global _runner
    if _runner is None:
        _runner = EvalRunner()
    return _runner
