import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.runtime_paths import runtime_dir
from app.security import is_relative_to, redact_sensitive_text

# 项目数据存储目录
PROJECTS_DIR = runtime_dir("projects")
RECENT_FILE = PROJECTS_DIR / "recent.json"

# 文件树中排除的目录和文件模式
EXCLUDE_PATTERNS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    ".next", "dist", "build", ".pytest_cache", ".mypy_cache",
    ".idea", ".vscode", ".vs", "*.pyc", "*.pyo", ".egg-info",
    "coverage", ".coverage", "htmlcov", ".tox"
}

EXCLUDE_PREFIXES = (".",)


def _should_exclude(name: str) -> bool:
    """判断文件/目录名是否应被排除"""
    if name in EXCLUDE_PATTERNS:
        return True
    if any(name.startswith(p) for p in EXCLUDE_PREFIXES):
        # 但保留 .github, .vscode 等常见项目目录
        if name in {".github", ".vscode", ".dockerignore", ".gitignore",
                    ".env.example", ".prettierrc", ".eslintrc"}:
            return False
        return True
    return False


class ProjectManager:
    """管理当前打开的项目和最近项目列表"""

    _current_project: Optional[Dict[str, Any]] = None
    _lock = threading.Lock()

    @classmethod
    def _history_file(cls) -> Path:
        return PROJECTS_DIR / "project_history.json"

    @classmethod
    def history_key(cls, path: str | Path | None) -> str:
        return str(path or "").replace("\\", "/").rstrip("/").lower()

    @classmethod
    def _now_iso(cls) -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _normalized_path(cls, path: str | Path) -> str:
        try:
            return str(Path(path).expanduser().resolve())
        except (OSError, RuntimeError, ValueError):
            return str(path)

    @classmethod
    def _load_history(cls) -> Dict[str, Dict[str, Any]]:
        path = cls._history_file()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        projects = data.get("projects") if isinstance(data, dict) else None
        if not isinstance(projects, dict):
            return {}
        normalized: Dict[str, Dict[str, Any]] = {}
        for key, entry in projects.items():
            if not isinstance(entry, dict):
                continue
            entry_path = str(entry.get("path") or "")
            item_key = cls.history_key(entry_path) or str(key)
            if not item_key:
                continue
            normalized[item_key] = dict(entry, path=entry_path or str(key))
        return normalized

    @classmethod
    def _save_history(cls, projects: Dict[str, Dict[str, Any]]) -> None:
        path = cls._history_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"projects": projects}, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as e:
            print(f"[ProjectManager] Failed to save project history: {e}")

    @classmethod
    def _update_history_entry(cls, path: str | Path, updates: Dict[str, Any]) -> Dict[str, Any]:
        normalized_path = cls._normalized_path(path)
        key = cls.history_key(normalized_path)
        if not key:
            raise ValueError("Project path is required")
        projects = cls._load_history()
        entry = dict(projects.get(key) or {})
        entry["path"] = normalized_path
        for field, value in updates.items():
            if value is None:
                entry.pop(field, None)
            else:
                entry[field] = value
        entry["updated_at"] = cls._now_iso()
        projects[key] = entry
        cls._save_history(projects)
        return dict(entry)

    @classmethod
    def list_project_history(cls) -> List[Dict[str, Any]]:
        return list(cls._load_history().values())

    @classmethod
    def get_project_history(cls, path: str | Path) -> Dict[str, Any]:
        key = cls.history_key(cls._normalized_path(path))
        return dict(cls._load_history().get(key) or {})

    @classmethod
    def set_project_pinned(cls, path: str | Path, pinned: bool) -> Dict[str, Any]:
        return cls._update_history_entry(path, {"pinned_at": cls._now_iso() if pinned else None})

    @classmethod
    def rename_project_display(cls, path: str | Path, name: str) -> Dict[str, Any]:
        display_name = (name or "").strip()
        if not display_name:
            raise ValueError("Project name is required")
        if len(display_name) > 80:
            raise ValueError("Project name is too long")
        return cls._update_history_entry(path, {"display_name": display_name})

    @classmethod
    def remove_project_from_history(cls, path: str | Path) -> Dict[str, Any]:
        now = cls._now_iso()
        return cls._update_history_entry(path, {"removed_at": now, "archived_at": now})

    @classmethod
    def restore_project_to_history(cls, path: str | Path) -> Dict[str, Any]:
        return cls._update_history_entry(path, {"removed_at": None, "archived_at": None})

    @classmethod
    def _build_project_info(cls, project_path: Path, last_opened: Optional[str] = None) -> Dict[str, Any]:
        git_info = cls._get_git_info(project_path)
        return {
            "path": str(project_path),
            "name": project_path.name,
            "git_branch": git_info.get("branch"),
            "git_remote": git_info.get("remote_url"),
            "git_ahead": git_info.get("ahead", 0),
            "git_behind": git_info.get("behind", 0),
            "git_modified": git_info.get("modified", 0),
            "git_untracked": git_info.get("untracked", 0),
            "git_staged": git_info.get("staged", 0),
            "last_opened": last_opened or datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def _load_recent(cls) -> List[Dict[str, Any]]:
        if RECENT_FILE.exists():
            try:
                with open(RECENT_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return []

    @classmethod
    def _save_recent(cls, projects: List[Dict[str, Any]]) -> None:
        try:
            tmp = RECENT_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(projects, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, RECENT_FILE)
        except OSError as e:
            print(f"[ProjectManager] Failed to save recent projects: {e}")

    @classmethod
    def _get_git_info(cls, path: Path) -> Dict[str, Any]:
        """获取项目的 git 信息"""
        info: Dict[str, Any] = {
            "branch": None,
            "remote_url": None,
            "ahead": 0,
            "behind": 0,
            "modified": 0,
            "untracked": 0,
            "staged": 0,
        }
        git_dir = path / ".git"
        if not git_dir.exists():
            return info

        try:
            # 当前分支
            result = subprocess.run(
                ["git", "-C", str(path), "branch", "--show-current"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                info["branch"] = result.stdout.strip() or None

            # Remote URL
            result = subprocess.run(
                ["git", "-C", str(path), "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                info["remote_url"] = redact_sensitive_text(result.stdout.strip()) or None

            # Ahead/behind
            if info["branch"]:
                result = subprocess.run(
                    ["git", "-C", str(path), "rev-list", "--left-right",
                     f"--count", f"origin/{info['branch']}...{info['branch']}"],
                    capture_output=True, text=True, timeout=5,
                    encoding="utf-8", errors="replace",
                )
                if result.returncode == 0:
                    parts = result.stdout.strip().split("\t")
                    if len(parts) == 2:
                        info["behind"] = int(parts[0])
                        info["ahead"] = int(parts[1])

            # Status counts
            result = subprocess.run(
                ["git", "-C", str(path), "status", "--short"],
                capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue
                    status = line[:2]
                    if status.startswith("??"):
                        info["untracked"] += 1
                    elif " " in status or status.startswith("M") or status.startswith("A") or status.startswith("D"):
                        if status[0] != " ":
                            info["staged"] += 1
                        if status[1] != " ":
                            info["modified"] += 1
        except (subprocess.TimeoutExpired, OSError, ValueError):
            pass

        return info

    @classmethod
    def open_project(cls, path: str) -> Dict[str, Any]:
        """打开项目，验证路径，持久化到最近列表"""
        project_path = Path(path).resolve()
        if not project_path.exists():
            raise ValueError(f"路径不存在: {path}")
        if not project_path.is_dir():
            raise ValueError(f"路径不是目录: {path}")

        project = cls._build_project_info(project_path)

        cls._lock.acquire()
        try:
            cls._current_project = project
        finally:
            cls._lock.release()

        # 更新最近列表
        recent = cls._load_recent()
        # 去重并移到顶部
        recent = [p for p in recent if p.get("path") != str(project_path)]
        recent.insert(0, project)
        recent = recent[:20]  # 最多保留 20 个
        cls._save_recent(recent)
        cls.restore_project_to_history(project_path)

        return project

    @classmethod
    def close_project(cls) -> None:
        """关闭当前项目"""
        with cls._lock:
            cls._current_project = None

    @classmethod
    def get_current(cls) -> Optional[Dict[str, Any]]:
        """返回当前项目信息"""
        with cls._lock:
            return dict(cls._current_project) if cls._current_project else None

    @classmethod
    def refresh_current(cls) -> Optional[Dict[str, Any]]:
        """Refresh current project metadata without changing recent project ordering."""
        with cls._lock:
            current = dict(cls._current_project) if cls._current_project else None
        if not current:
            return None

        project_path = Path(current["path"]).resolve()
        if not project_path.exists():
            raise ValueError(f"Path does not exist: {project_path}")
        if not project_path.is_dir():
            raise ValueError(f"Path is not a directory: {project_path}")

        refreshed = cls._build_project_info(project_path, current.get("last_opened"))
        with cls._lock:
            cls._current_project = refreshed
        return dict(refreshed)

    @classmethod
    def list_recent(cls) -> List[Dict[str, Any]]:
        """返回最近打开的项目列表"""
        return cls._load_recent()

    @classmethod
    def create_project(cls, parent_path: str, name: str, template: str = "empty") -> Dict[str, Any]:
        """在指定父目录下创建新项目"""
        parent = Path(parent_path).resolve()
        if not parent.exists() or not parent.is_dir():
            raise ValueError(f"父目录不存在: {parent_path}")

        name_path = Path(name)
        if name_path.is_absolute() or name_path.name != name or name in {"", ".", ".."}:
            raise ValueError(f"Invalid project name: {name}")

        project_path = (parent / name).resolve()
        if not is_relative_to(project_path, parent):
            raise ValueError(f"Project path escapes parent directory: {project_path}")
        if project_path.exists():
            raise ValueError(f"目录已存在: {project_path}")

        project_path.mkdir(parents=True)

        # 根据模板初始化项目结构
        if template == "python":
            (project_path / "src").mkdir()
            (project_path / "tests").mkdir()
            (project_path / "requirements.txt").write_text("# Python dependencies\n", encoding="utf-8")
            (project_path / "main.py").write_text('def main():\n    print("Hello, World!")\n\nif __name__ == "__main__":\n    main()\n', encoding="utf-8")
            (project_path / ".gitignore").write_text("__pycache__/\n*.pyc\n.venv/\nvenv/\n.env\n", encoding="utf-8")
        elif template == "react":
            (project_path / "src").mkdir()
            (project_path / "public").mkdir()
            (project_path / "package.json").write_text(json.dumps({
                "name": name,
                "version": "1.0.0",
                "private": True,
                "dependencies": {"react": "^18.3.1", "react-dom": "^18.3.1"},
                "devDependencies": {"vite": "^6.0.0", "@vitejs/plugin-react": "^4.3.3"},
                "scripts": {"dev": "vite", "build": "vite build"}
            }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            (project_path / "index.html").write_text('<!DOCTYPE html>\n<html>\n<head><title>' + name + '</title></head>\n<body><div id="root"></div><script type="module" src="/src/main.jsx"></script></body>\n</html>\n', encoding="utf-8")
            (project_path / "src" / "main.jsx").write_text('import React from "react";\nimport ReactDOM from "react-dom/client";\nimport App from "./App";\n\nReactDOM.createRoot(document.getElementById("root")).render(<App />);\n', encoding="utf-8")
            (project_path / "src" / "App.jsx").write_text('export default function App() {\n  return <div>Hello, ' + name + '!</div>;\n}\n', encoding="utf-8")
            (project_path / "vite.config.js").write_text('import { defineConfig } from "vite";\nimport react from "@vitejs/plugin-react";\n\nexport default defineConfig({\n  plugins: [react()],\n});\n', encoding="utf-8")
            (project_path / ".gitignore").write_text("node_modules/\ndist/\n.env\n", encoding="utf-8")
        elif template == "nodejs":
            (project_path / "package.json").write_text(json.dumps({
                "name": name,
                "version": "1.0.0",
                "main": "index.js",
                "scripts": {"start": "node index.js"}
            }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            (project_path / "index.js").write_text('console.log("Hello, ' + name + '!");\n', encoding="utf-8")
            (project_path / ".gitignore").write_text("node_modules/\n.env\n", encoding="utf-8")
        else:
            # empty template - just create README
            (project_path / "README.md").write_text(f"# {name}\n\n", encoding="utf-8")
            (project_path / ".gitignore").write_text("# Add your ignore patterns here\n", encoding="utf-8")

        # 初始化 git
        try:
            subprocess.run(
                ["git", "init"], cwd=str(project_path),
                capture_output=True, timeout=10
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

        return cls.open_project(str(project_path))

    @classmethod
    def get_tree(cls, relative_path: str = "") -> List[Dict[str, Any]]:
        """返回项目目录树"""
        project = cls._current_project
        if not project:
            return []

        base = Path(project["path"]).resolve()
        target = base / relative_path if relative_path else base
        target = target.resolve()

        # 安全检查
        if not is_relative_to(target, base):
            return []

        if not target.exists():
            return []

        def has_visible_children(path: Path) -> bool:
            try:
                return any(not _should_exclude(child.name) for child in path.iterdir())
            except PermissionError:
                return False

        def build_tree(path: Path) -> List[Dict[str, Any]]:
            nodes = []
            try:
                for item in sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                    if _should_exclude(item.name):
                        continue
                    rel = str(item.relative_to(base)).replace("\\", "/")
                    node: Dict[str, Any] = {
                        "name": item.name,
                        "type": "dir" if item.is_dir() else "file",
                        "path": rel,
                    }
                    if item.is_file():
                        node["extension"] = item.suffix.lstrip(".")
                    if item.is_dir():
                        node["has_children"] = has_visible_children(item)
                        # 限制递归深度：仅当目录不太深时递归
                        depth = len(Path(rel).parts)
                        if depth < 3:
                            children: List[Dict[str, Any]] = build_tree(item)
                            if children:
                                node["children"] = children
                    nodes.append(node)
            except PermissionError:
                pass
            return nodes

        return build_tree(target)
