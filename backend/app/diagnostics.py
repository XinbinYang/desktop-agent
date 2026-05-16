"""Diagnostics collector — run linters/typecheckers and collect Problems."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class DiagnosticItem:
    file_path: str
    line: int = 0
    column: int = 0
    severity: str = "error"  # error, warning, info
    message: str = ""
    source: str = ""  # mypy, tsc, eslint, pyright


@dataclass
class DiagnosticsResult:
    source: str
    total: int = 0
    errors: int = 0
    warnings: int = 0
    items: List[DiagnosticItem] = field(default_factory=list)
    raw_output: str = ""


_last_result: Optional[DiagnosticsResult] = None


# ── detection ───────────────────────────────────────────────────────────────

def detect_linters(project_path: str) -> List[str]:
    """Detect which linters/typecheckers are available for the project."""
    root = Path(project_path)
    available: List[str] = []

    # Python: mypy
    if list(root.glob("**/*.py")):
        if (root / "mypy.ini").exists() or (root / "pyproject.toml").exists():
            available.append("mypy")
        else:
            available.append("mypy")  # Can still run with defaults

    # Python: pyright (if installed)
    available.append("pyright")  # Assume it might be available

    # TypeScript: tsc
    if (root / "tsconfig.json").exists():
        available.append("tsc")

    # TypeScript: eslint
    if (root / "eslint.config.js").exists() or (root / "eslint.config.mjs").exists() or (root / ".eslintrc.js").exists():
        available.append("eslint")

    return available


# ── parsers ─────────────────────────────────────────────────────────────────

def _parse_mypy(output: str, project_path: str) -> List[DiagnosticItem]:
    items: List[DiagnosticItem] = []
    # mypy output: file:line:col: severity: message
    # e.g.: src/app/main.py:42:5: error: Incompatible types...
    pattern = re.compile(
        r"^(.+?):(\d+):(\d+)?:\s*(error|warning|note):\s*(.+)$",
        re.MULTILINE,
    )
    for m in pattern.finditer(output):
        file_path = m.group(1)
        line = int(m.group(2))
        col = int(m.group(3) or 0)
        severity_raw = m.group(4)
        msg = m.group(5).strip()
        severity = {"error": "error", "warning": "warning", "note": "info"}.get(severity_raw, "warning")
        items.append(DiagnosticItem(
            file_path=file_path, line=line, column=col,
            severity=severity, message=msg, source="mypy",
        ))
    return items


def _parse_tsc(output: str) -> List[DiagnosticItem]:
    items: List[DiagnosticItem] = []
    # tsc output: file(line,col): error TS1234: message
    pattern = re.compile(
        r"^(.+?)\((\d+),(\d+)\):\s*(error|warning)\s+TS(\d+):\s*(.+)$",
        re.MULTILINE,
    )
    for m in pattern.finditer(output):
        items.append(DiagnosticItem(
            file_path=m.group(1), line=int(m.group(2)), column=int(m.group(3)),
            severity="error" if m.group(4) == "error" else "warning",
            message=f"TS{m.group(5)}: {m.group(6).strip()}", source="tsc",
        ))
    return items


def _parse_eslint(output: str) -> List[DiagnosticItem]:
    items: List[DiagnosticItem] = []
    # eslint output: file:line:col  severity  message  rule
    pattern = re.compile(
        r"^\s*(.+?):(\d+):(\d+)\s+(error|warning)\s+(.+?)\s{2,}(.+)$",
        re.MULTILINE,
    )
    for m in pattern.finditer(output):
        items.append(DiagnosticItem(
            file_path=m.group(1), line=int(m.group(2)), column=int(m.group(3)),
            severity=m.group(4), message=m.group(5).strip(), source="eslint",
        ))
    # Also try JSON output format
    if not items and output.strip().startswith("["):
        try:
            data = json.loads(output)
            for entry in data:
                if isinstance(entry, dict):
                    items.append(DiagnosticItem(
                        file_path=entry.get("filePath", ""),
                        line=entry.get("line", 0),
                        column=entry.get("column", 0),
                        severity=entry.get("severity", "error") == "error" and "error" or "warning",
                        message=entry.get("message", ""),
                        source="eslint",
                    ))
        except (json.JSONDecodeError, TypeError):
            pass
    return items


def _parse_pyright(output: str) -> List[DiagnosticItem]:
    items: List[DiagnosticItem] = []
    # pyright output: file:line:col - severity: message
    pattern = re.compile(
        r"^\s*(.+?):(\d+):(\d+)\s*-\s*(error|warning|information):\s*(.+)$",
        re.MULTILINE,
    )
    for m in pattern.finditer(output):
        sev = {"error": "error", "warning": "warning", "information": "info"}.get(m.group(4), "warning")
        items.append(DiagnosticItem(
            file_path=m.group(1), line=int(m.group(2)), column=int(m.group(3)),
            severity=sev, message=m.group(5).strip(), source="pyright",
        ))
    return items


# ── runner ──────────────────────────────────────────────────────────────────

async def run_diagnostics(
    project_path: str,
    sources: Optional[List[str]] = None,
    event_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> List[DiagnosticsResult]:
    """Run diagnostics for the project and return structured results."""
    global _last_result

    if sources is None:
        sources = detect_linters(project_path)

    results: List[DiagnosticsResult] = []

    for source in sources:
        if event_callback:
            event_callback({
                "type": "diagnostics_start",
                "data": {"source": source},
            })

        cmd = _build_command(source, project_path)
        if not cmd:
            continue

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=project_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=120
            )
        except asyncio.TimeoutError:
            results.append(DiagnosticsResult(source=source, raw_output="Timed out (2 min)"))
            continue
        except Exception as e:
            results.append(DiagnosticsResult(source=source, raw_output=str(e)))
            continue

        output = (stdout or b"").decode("utf-8", errors="replace")
        if stderr:
            output += "\n" + (stderr or b"").decode("utf-8", errors="replace")

        # Parse
        parser = {
            "mypy": _parse_mypy,
            "tsc": _parse_tsc,
            "eslint": _parse_eslint,
            "pyright": _parse_pyright,
        }.get(source, lambda o, _: [])

        items = parser(output, project_path) if source == "mypy" else parser(output)
        errors = sum(1 for i in items if i.severity == "error")
        warnings = sum(1 for i in items if i.severity == "warning")

        result = DiagnosticsResult(
            source=source,
            total=len(items),
            errors=errors,
            warnings=warnings,
            items=items,
            raw_output=output[:5000],
        )
        results.append(result)
        _last_result = result

        if event_callback:
            event_callback({
                "type": "diagnostics_complete",
                "data": {
                    "source": source,
                    "total": result.total,
                    "errors": result.errors,
                    "warnings": result.warnings,
                    "items": [
                        {"file_path": i.file_path, "line": i.line, "column": i.column,
                         "severity": i.severity, "message": i.message, "source": i.source}
                        for i in items[:200]
                    ],
                },
            })

    return results


def _build_command(source: str, project_path: str) -> Optional[List[str]]:
    root = Path(project_path)
    if source == "mypy":
        config_args = []
        if (root / "mypy.ini").exists():
            config_args = ["--config-file", str(root / "mypy.ini")]
        return ["python", "-m", "mypy", *config_args, "--no-error-summary", str(root)]

    if source == "pyright":
        node = "npx.cmd" if os.name == "nt" else "npx"
        return [node, "pyright", "--outputjson", str(root)]

    if source == "tsc":
        node = "npx.cmd" if os.name == "nt" else "npx"
        return [node, "tsc", "--noEmit", "--pretty", "false"]

    if source == "eslint":
        node = "npx.cmd" if os.name == "nt" else "npx"
        return [node, "eslint", str(root), "--format", "json"]

    return None


def get_last_result() -> Optional[DiagnosticsResult]:
    return _last_result
