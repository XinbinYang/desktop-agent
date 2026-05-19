"""Integrated test runner — discover and execute project tests."""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple


@dataclass
class TestResult:
    __test__ = False

    name: str
    status: str  # passed, failed, skipped, error
    duration_ms: float = 0
    message: str = ""
    file_path: str = ""


@dataclass
class TestRun:
    __test__ = False

    run_id: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_ms: float = 0
    results: List[TestResult] = field(default_factory=list)
    raw_output: str = ""


# ── framework detection ─────────────────────────────────────────────────────

def detect_framework(project_path: str) -> Optional[str]:
    """Detect the test framework used by the project."""
    root = Path(project_path)
    if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists():
        try:
            content = (root / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
            if "pytest" in content:
                return "pytest"
        except OSError:
            pass
    if (root / "conftest.py").exists() or list(root.glob("**/test_*.py")):
        return "pytest"
    if (root / "vitest.config.ts").exists() or (root / "vitest.config.js").exists():
        return "vitest"
    if (root / "jest.config.ts").exists() or (root / "jest.config.js").exists():
        return "jest"
    if (root / "package.json").exists():
        try:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                test_script = scripts["test"]
                if "vitest" in test_script:
                    return "vitest"
                if "jest" in test_script:
                    return "jest"
        except (OSError, json.JSONDecodeError):
            pass
    return None


# ── parsers ─────────────────────────────────────────────────────────────────

def _parse_pytest_output(output: str) -> List[TestResult]:
    results: List[TestResult] = []
    # Match: tests/test_file.py::TestClass::test_name PASSED [  xx%]
    pattern = re.compile(
        r"^(.*?\.py)::(.*?)\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)",
        re.MULTILINE,
    )
    for m in pattern.finditer(output):
        file_path = m.group(1)
        name = m.group(2)
        status_raw = m.group(3).lower()
        status = {
            "passed": "passed", "failed": "failed", "error": "error",
            "skipped": "skipped", "xfail": "skipped", "xpass": "passed",
        }.get(status_raw, "failed")
        results.append(TestResult(name=name, status=status, file_path=file_path))
    return results


def _parse_jest_output(output: str) -> List[TestResult]:
    results: List[TestResult] = []
    # Match: ✓ / ✗ / ○ test name (file.tsx)
    pattern = re.compile(
        r"^\s*([✓✗○])\s+(.+?)\s+\((\d+)\s*ms\).*$",
        re.MULTILINE,
    )
    for m in pattern.finditer(output):
        symbol = m.group(1)
        name = m.group(2)
        duration = float(m.group(3))
        status = {"✓": "passed", "✗": "failed", "○": "skipped"}.get(symbol, "failed")
        results.append(TestResult(name=name.strip(), status=status, duration_ms=duration))
    return results


# ── runner ──────────────────────────────────────────────────────────────────

async def run_tests(
    project_path: str,
    framework: Optional[str] = None,
    filter_pattern: str = "",
    event_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> TestRun:
    """Run project tests and stream results via event_callback."""
    run_id = f"test_{int(time.time() * 1000)}"

    if not framework:
        framework = detect_framework(project_path)

    if not framework:
        run = TestRun(run_id=run_id)
        run.raw_output = "No test framework detected in project."
        return run

    # Build command
    if framework == "pytest":
        cmd = ["python", "-m", "pytest", "-v", "--tb=short"]
        if filter_pattern:
            cmd.extend(["-k", filter_pattern])
    elif framework in ("vitest", "jest"):
        node_cmd = "npx.cmd" if os.name == "nt" else "npx"
        cmd = [node_cmd, framework, "--run", "--reporter=verbose"]
        if filter_pattern:
            cmd.extend(["-t", filter_pattern])
    else:
        run = TestRun(run_id=run_id)
        run.raw_output = f"Unsupported framework: {framework}"
        return run

    if event_callback:
        event_callback({
            "type": "test_run_start",
            "data": {"run_id": run_id, "framework": framework, "command": " ".join(cmd)},
        })

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=project_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=300
        )
    except asyncio.TimeoutError:
        run = TestRun(run_id=run_id)
        run.errors = 1
        run.raw_output = "Test run timed out (5 minutes)."
        return run
    except Exception as e:
        run = TestRun(run_id=run_id)
        run.errors = 1
        run.raw_output = f"Test run failed: {e}"
        return run

    output = (stdout or b"").decode("utf-8", errors="replace")
    if stderr:
        output += "\n" + (stderr or b"").decode("utf-8", errors="replace")

    # Parse results
    if framework == "pytest":
        results = _parse_pytest_output(output)
    else:
        results = _parse_jest_output(output)

    passed = sum(1 for r in results if r.status == "passed")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")
    errors = sum(1 for r in results if r.status == "error")

    run = TestRun(
        run_id=run_id,
        total=len(results),
        passed=passed,
        failed=failed,
        skipped=skipped,
        errors=errors,
        results=results,
        raw_output=output,
    )

    if event_callback:
        event_callback({
            "type": "test_run_complete",
            "data": {
                "run_id": run_id,
                "framework": framework,
                "total": run.total,
                "passed": run.passed,
                "failed": run.failed,
                "skipped": run.skipped,
                "errors": run.errors,
                "results": [{"name": r.name, "status": r.status, "duration_ms": r.duration_ms, "file_path": r.file_path} for r in results],
            },
        })

    return run


def get_last_run() -> Optional[TestRun]:
    """Return the most recent test run result (in-memory cache)."""
    return _last_run


_last_run: Optional[TestRun] = None


async def run_and_store(
    project_path: str,
    framework: Optional[str] = None,
    filter_pattern: str = "",
    event_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> TestRun:
    global _last_run
    _last_run = await run_tests(project_path, framework, filter_pattern, event_callback)
    return _last_run
