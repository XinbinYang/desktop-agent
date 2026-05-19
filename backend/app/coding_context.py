"""Codebase context helpers for coding-agent workflows."""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.project_manager import ProjectManager


IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

TEXT_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".css",
    ".html",
    ".ps1",
    ".bat",
}

LANGUAGE_BY_EXT = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript React",
    ".js": "JavaScript",
    ".jsx": "JavaScript React",
    ".json": "JSON",
    ".md": "Markdown",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".css": "CSS",
    ".html": "HTML",
}


def current_project_path() -> Optional[Path]:
    project = ProjectManager.get_current()
    if not project:
        return None
    try:
        return Path(project["path"]).resolve()
    except (KeyError, OSError, ValueError):
        return None


def iter_project_files(root: Path, max_files: int = 800) -> Iterable[Path]:
    count = 0
    for path in root.rglob("*"):
        if count >= max_files:
            break
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        count += 1
        yield path


def _safe_read(path: Path, limit: int = 250_000) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def outline_python(path: Path, text: str) -> List[Dict[str, Any]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    symbols: List[Dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            symbols.append({
                "kind": "function",
                "name": node.name,
                "line": node.lineno,
                "signature": f"{node.name}({', '.join(args)})",
            })
        elif isinstance(node, ast.ClassDef):
            symbols.append({"kind": "class", "name": node.name, "line": node.lineno})
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append({
                        "kind": "method",
                        "name": f"{node.name}.{child.name}",
                        "line": child.lineno,
                    })
    return symbols


TS_SYMBOL_PATTERNS = [
    ("class", re.compile(r"^\s*export\s+class\s+([A-Za-z0-9_]+)|^\s*class\s+([A-Za-z0-9_]+)")),
    ("function", re.compile(r"^\s*export\s+function\s+([A-Za-z0-9_]+)|^\s*function\s+([A-Za-z0-9_]+)")),
    ("component", re.compile(r"^\s*export\s+const\s+([A-Z][A-Za-z0-9_]*)\s*[:=]|^\s*const\s+([A-Z][A-Za-z0-9_]*)\s*[:=]")),
    ("export", re.compile(r"^\s*export\s+(?:interface|type|enum)\s+([A-Za-z0-9_]+)")),
]


def outline_typescript(text: str) -> List[Dict[str, Any]]:
    symbols: List[Dict[str, Any]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in TS_SYMBOL_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            name = next((g for g in match.groups() if g), "")
            if name:
                symbols.append({"kind": kind, "name": name, "line": idx})
                break
    return symbols


def outline_file(path: Path) -> Dict[str, Any]:
    text = _safe_read(path)
    suffix = path.suffix.lower()
    symbols: List[Dict[str, Any]]
    if suffix == ".py":
        symbols = outline_python(path, text)
    elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
        symbols = outline_typescript(text)
    else:
        symbols = []
    imports = []
    for idx, line in enumerate(text.splitlines()[:300], start=1):
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")) or stripped.startswith("const ") and "require(" in stripped:
            imports.append({"line": idx, "text": stripped[:160]})
    return {
        "path": str(path),
        "language": LANGUAGE_BY_EXT.get(suffix, suffix.lstrip(".") or "text"),
        "lines": text.count("\n") + (1 if text else 0),
        "imports": imports[:30],
        "symbols": symbols[:80],
    }


def detect_commands(root: Path) -> Dict[str, str]:
    commands: Dict[str, str] = {}
    package_json = root / "package.json"
    if package_json.exists():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = data.get("scripts") or {}
            for key in ("test", "lint", "typecheck", "build"):
                if key in scripts:
                    commands[key] = f"npm run {key}"
        except (OSError, ValueError):
            pass
    if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists() or (root / "tests").exists():
        commands.setdefault("test", "python -m pytest")
    return commands


def build_repo_map(project_path: Optional[str] = None, max_files: int = 220) -> Dict[str, Any]:
    if project_path:
        root = Path(project_path).resolve()
    else:
        root = current_project_path()
    if root is None:
        return {"error": "No project is currently open"}
    if not root.exists() or not root.is_dir():
        return {"error": f"Project path is not a directory: {root}"}

    files = list(iter_project_files(root, max_files=max_files))
    language_counts = Counter(LANGUAGE_BY_EXT.get(p.suffix.lower(), p.suffix.lower() or "text") for p in files)
    outlines = []
    for path in files:
        if path.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx"}:
            item = outline_file(path)
            if item["symbols"]:
                item["path"] = str(path.relative_to(root))
                outlines.append(item)
        if len(outlines) >= 50:
            break

    entrypoints = []
    for name in ("README.md", "package.json", "pyproject.toml", "pytest.ini", "backend/app/main.py", "frontend/src/App.tsx"):
        candidate = root / name
        if candidate.exists():
            entrypoints.append(name)

    return {
        "project_path": str(root),
        "languages": dict(language_counts.most_common()),
        "entrypoints": entrypoints,
        "commands": detect_commands(root),
        "files_scanned": len(files),
        "outlines": outlines,
    }


def format_repo_map_summary(repo_map: Dict[str, Any], max_chars: int = 5000) -> str:
    if repo_map.get("error"):
        return f"Repo map unavailable: {repo_map['error']}"
    lines = [
        "## Repo Map",
        f"Project: {repo_map.get('project_path')}",
        f"Languages: {repo_map.get('languages')}",
        f"Entrypoints: {', '.join(repo_map.get('entrypoints') or []) or 'none detected'}",
        f"Commands: {repo_map.get('commands') or {}}",
        "Key symbols:",
    ]
    for item in repo_map.get("outlines", [])[:30]:
        symbols = ", ".join(f"{s['kind']} {s['name']}:{s['line']}" for s in item.get("symbols", [])[:8])
        if symbols:
            lines.append(f"- {item['path']}: {symbols}")
    text = "\n".join(lines)
    return text[:max_chars]


def run_code_search(
    query: str,
    root: Path,
    path: str = "",
    file_glob: str = "",
    context_lines: int = 2,
    max_results: int = 80,
) -> str:
    search_root = (root / path).resolve() if path else root
    if not str(search_root).startswith(str(root.resolve())):
        return f"[ERROR] Search path escapes project: {path}"
    if not search_root.exists():
        return f"[ERROR] Search path does not exist: {path or root}"

    rg = shutil.which("rg")
    if rg:
        cmd = [
            rg,
            "--line-number",
            "--with-filename",
            "--ignore-case",
            "--context",
            str(max(0, min(context_lines, 5))),
            "--max-count",
            str(max_results),
        ]
        if file_glob:
            cmd.extend(["--glob", file_glob])
        cmd.extend([query, str(search_root)])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, encoding="utf-8", errors="replace")
            output = (result.stdout or result.stderr).strip()
            return output[:40_000] if output else "No matches"
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"[ERROR] code_search failed: {exc}"

    matches: List[str] = []
    for fp in iter_project_files(search_root, max_files=1000):
        if file_glob and not fp.match(file_glob):
            continue
        text = _safe_read(fp, limit=500_000)
        lines = text.splitlines()
        for idx, line in enumerate(lines, start=1):
            if query.lower() not in line.lower():
                continue
            start = max(1, idx - context_lines)
            end = min(len(lines), idx + context_lines)
            rel = fp.relative_to(root)
            snippet = "\n".join(f"{rel}:{i}:{lines[i-1]}" for i in range(start, end + 1))
            matches.append(snippet)
            if len(matches) >= max_results:
                return "\n--\n".join(matches)
    return "\n--\n".join(matches) if matches else "No matches"
