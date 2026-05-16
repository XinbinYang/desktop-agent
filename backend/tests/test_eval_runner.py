"""Tests for Agent Eval Runner — manifest loading, scoring, comparison."""
from pathlib import Path
from app.eval_runner import (
    EvalTask,
    EvalResult,
    EvalRun,
    EvalRunner,
    load_manifest,
)


class TestEvalTask:
    def test_from_manifest(self):
        data = {"id": "task-1", "category": "bugfix", "prompt": "fix the bug", "verification": "pytest"}
        task = EvalTask.from_manifest(data)
        assert task.id == "task-1"
        assert task.category == "bugfix"
        assert task.prompt == "fix the bug"
        assert task.verification == "pytest"

    def test_empty_fields(self):
        task = EvalTask.from_manifest({})
        assert task.id == ""


class TestEvalResult:
    def test_defaults(self):
        result = EvalResult(task_id="t1", passed=False)
        assert result.passed == False
        assert result.iterations == 0
        assert result.files_changed == []

    def test_to_dict(self):
        result = EvalResult(task_id="t1", passed=True, iterations=5, tool_calls=12)
        d = result.to_dict()
        assert d["task_id"] == "t1"
        assert d["passed"] == True
        assert d["iterations"] == 5

    def test_to_dict_with_error(self):
        result = EvalResult(task_id="t2", passed=False, error="timeout")
        d = result.to_dict()
        assert d["error"] == "timeout"


class TestEvalRun:
    def test_dataclass(self):
        run = EvalRun(run_id="run-1")
        assert run.status == "idle"
        assert run.success_rate is None
        assert run.results == []

    def test_success_rate_calculation(self):
        run = EvalRun(run_id="run-1", results=[
            EvalResult(task_id="t1", passed=True),
            EvalResult(task_id="t2", passed=True),
            EvalResult(task_id="t3", passed=False),
        ])
        assert run.success_rate == 2 / 3

    def test_success_rate_empty(self):
        run = EvalRun(run_id="run-1")
        assert run.success_rate is None

    def test_to_dict(self):
        run = EvalRun(run_id="run-1", total_tasks=3, completed_tasks=2,
                      results=[EvalResult(task_id="t1", passed=True)])
        d = run.to_dict()
        assert d["run_id"] == "run-1"
        assert d["total_tasks"] == 3
        assert len(d["results"]) == 1


class TestEvalRunner:
    def test_singleton(self):
        from app.eval_runner import get_eval_runner
        r1 = get_eval_runner()
        r2 = get_eval_runner()
        assert r1 is r2

    def test_compare_runs_improvement(self):
        runner = EvalRunner()
        r1 = EvalRun(run_id="before", results=[
            EvalResult(task_id="t1", passed=False, iterations=8),
        ])
        r2 = EvalRun(run_id="after", results=[
            EvalResult(task_id="t1", passed=True, iterations=4),
        ])
        runner._history = [r1, r2]

        comp = runner.compare_runs("before", "after")
        assert comp is not None
        assert comp["comparisons"][0]["change"] == "improvement"

    def test_compare_runs_regression(self):
        runner = EvalRunner()
        r1 = EvalRun(run_id="before", results=[
            EvalResult(task_id="t1", passed=True),
        ])
        r2 = EvalRun(run_id="after", results=[
            EvalResult(task_id="t1", passed=False),
        ])
        runner._history = [r1, r2]
        comp = runner.compare_runs("before", "after")
        assert comp["comparisons"][0]["change"] == "regression"

    def test_compare_runs_not_found(self):
        runner = EvalRunner()
        assert runner.compare_runs("x", "y") is None

    def test_history_keeps_all(self):
        """History is capped inside run_all(), not on direct append."""
        runner = EvalRunner()
        for i in range(12):
            runner._history.append(EvalRun(run_id=str(i)))
        assert len(runner._history) == 12
        assert runner._history[-1].run_id == "11"


class TestLoadManifest:
    def test_loads_real_manifest(self):
        tasks, err = load_manifest()
        assert err is None, f"Error loading manifest: {err}"
        assert len(tasks) >= 10
        for task in tasks:
            assert task.id, f"Task has empty id: {task}"
            assert task.prompt, f"Task {task.id} has empty prompt"
            assert task.verification, f"Task {task.id} has empty verification"
