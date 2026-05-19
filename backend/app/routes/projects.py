import asyncio
import hashlib
import os
import re
import shlex
import subprocess
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path

from app.project_manager import ProjectManager
from app.credential_manager import CredentialManager
from app.coding_context import build_repo_map
from app.runtime_paths import runtime_dir
from app.security import is_relative_to, redact_sensitive_text, resolve_under_base
from app.project_rules import (
    PROJECT_RULES_FILE,
    USER_RULES_DIR,
    USER_RULES_FILE,
    get_project_rules,
    get_user_rules,
)

router = APIRouter()


class OpenProjectRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    path: str
    touch_recent: bool = True


class CreateProjectRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    parent_path: str
    name: str
    template: str = "empty"


class CloneProjectRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    url: str
    path: Optional[str] = None
    token: Optional[str] = None


class ProjectPathRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    path: str


class ProjectPinRequest(ProjectPathRequest):
    pinned: bool


class ProjectDisplayNameRequest(ProjectPathRequest):
    name: str


class PersistentWorktreeRequest(ProjectPathRequest):
    name: Optional[str] = None


class RenameProjectPathRequest(ProjectPathRequest):
    new_name: str


class ProjectRunRequest(ProjectPathRequest):
    action: Literal["run_file", "run_tests"]


RUN_FILE_EXTENSIONS = {".py", ".js", ".mjs", ".cjs", ".ps1", ".bat", ".cmd"}
JS_TEST_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}


def _current_project_root() -> tuple[Optional[Path], Optional[str]]:
    project = ProjectManager.get_current()
    if not project:
        return None, "No current project"
    try:
        return Path(project["path"]).resolve(), None
    except (OSError, ValueError) as e:
        return None, f"Invalid project path: {e}"


def _resolve_project_target(path: str) -> tuple[Optional[Path], Optional[Path], Optional[str]]:
    root, err = _current_project_root()
    if err or root is None:
        return root, None, err
    if not (path or "").strip():
        return root, None, "Path is required"

    target, err = resolve_under_base(path, root, allow_relative=True)
    if err:
        return root, None, err
    return root, target, None


def _relative_project_path(root: Path, target: Path) -> str:
    try:
        return target.relative_to(root).as_posix()
    except ValueError:
        return str(target)


def _validate_child_name(name: str) -> Optional[str]:
    trimmed = (name or "").strip()
    if not trimmed:
        return "New name is required"
    if trimmed in {".", ".."}:
        return "Invalid new name"
    if "/" in trimmed or "\\" in trimmed:
        return "New name cannot contain path separators"
    if Path(trimmed).is_absolute() or Path(trimmed).name != trimmed:
        return "Invalid new name"
    return None


def _send_to_trash(path: Path) -> None:
    from send2trash import send2trash

    send2trash(str(path))


def _command_display(command: list[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return " ".join(shlex.quote(part) for part in command)


def _run_git(args: list[str], cwd: Path, timeout: int = 30) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return (
            result.returncode,
            redact_sensitive_text(result.stdout or ""),
            redact_sensitive_text(result.stderr or ""),
        )
    except subprocess.TimeoutExpired:
        return 1, "", f"git command timed out after {timeout}s"
    except OSError as exc:
        return 1, "", str(exc)


def _project_id(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]


def _slugify_worktree_name(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip()).strip(".-")
    return slug[:64] or "worktree"


def _unique_worktree_target(parent: Path, slug: str) -> Path:
    target = parent / slug
    index = 2
    while target.exists():
        target = parent / f"{slug}-{index}"
        index += 1
    return target


def _build_run_command(root: Path, target: Path, action: str) -> tuple[Optional[list[str]], int, Optional[str]]:
    rel = _relative_project_path(root, target)
    ext = target.suffix.lower()

    if action == "run_file":
        if not target.is_file():
            return None, 0, "Run file requires a file path"
        if ext not in RUN_FILE_EXTENSIONS:
            return None, 0, f"Unsupported runnable file type: {ext or '(none)'}"
        if ext == ".py":
            return ["python", rel], 120, None
        if ext in {".js", ".mjs", ".cjs"}:
            return ["node", rel], 120, None
        if ext == ".ps1":
            shell = "powershell.exe" if os.name == "nt" else "pwsh"
            return [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", rel], 120, None
        return ["cmd", "/c", rel], 120, None

    if action == "run_tests":
        from app.test_runner import detect_framework

        framework = detect_framework(str(root))
        if framework == "pytest":
            return ["python", "-m", "pytest", "-v", "--tb=short", rel], 300, None
        node_cmd = "npx.cmd" if os.name == "nt" else "npx"
        if framework == "vitest":
            return [node_cmd, "vitest", "--run", "--reporter=verbose", rel], 300, None
        if framework == "jest":
            return [node_cmd, "jest", rel], 300, None
        if ext == ".py" or target.is_dir():
            return ["python", "-m", "pytest", "-v", "--tb=short", rel], 300, None
        if ext in JS_TEST_EXTENSIONS:
            return [node_cmd, "vitest", "--run", "--reporter=verbose", rel], 300, None
        return None, 0, "No supported test framework detected"

    return None, 0, f"Unsupported action: {action}"


async def _run_project_command(command: list[str], cwd: Path, timeout: int) -> dict[str, Any]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        return {"exit_code": None, "output": "", "error": f"Failed to start command: {e}"}

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"exit_code": None, "output": "", "error": f"Command timed out after {timeout}s"}

    out_text = (stdout or b"").decode("utf-8", errors="replace")
    err_text = (stderr or b"").decode("utf-8", errors="replace")
    output = out_text
    if err_text:
        output = f"{output}\n{err_text}" if output else err_text
    if len(output) > 16000:
        output = output[:16000] + "\n... output truncated ..."

    error = "" if proc.returncode == 0 else f"Exit code {proc.returncode}"
    return {"exit_code": proc.returncode, "output": output, "error": error}


@router.get("/api/projects")
def list_projects():
    """获取最近项目列表和当前项目"""
    return {
        "projects": ProjectManager.list_recent(),
        "current": ProjectManager.get_current()
    }


@router.get("/api/projects/current")
def get_current_project():
    """获取当前打开的项目"""
    return ProjectManager.get_current()


@router.get("/api/projects/repomap")
def get_project_repomap(max_files: int = 220):
    project = ProjectManager.get_current()
    if not project:
        return {"error": "No current project"}
    return build_repo_map(project["path"], max_files=max(20, min(max_files, 1000)))


@router.post("/api/projects/open")
def open_project(req: OpenProjectRequest):
    """打开一个项目目录"""
    try:
        project = ProjectManager.open_project(req.path, touch_recent=req.touch_recent)
        # 配置 GCM
        if req.touch_recent:
            CredentialManager.configure_gcm(project["path"])
        return project
    except ValueError as e:
        return {"error": str(e)}


@router.post("/api/projects/clone")
async def clone_project(req: CloneProjectRequest):
    """Clone a Git repository and open it as the current project."""
    from app.tools.git_tool import GitCloneTool

    try:
        if req.path:
            target = Path(req.path).resolve()
        else:
            repo_name = req.url.rstrip("/").split("/")[-1].replace(".git", "")
            current = ProjectManager.get_current()
            target = (Path(current["path"]).parent if current else Path.cwd()) / repo_name
            target = target.resolve()

        result = await GitCloneTool().execute(req.url, str(target), req.token)
        if result.error:
            return {"error": result.error}

        project = ProjectManager.open_project(str(target))
        CredentialManager.configure_gcm(str(target))
        project["message"] = result.output
        return project
    except ValueError as e:
        return {"error": str(e)}


@router.post("/api/projects/close")
def close_project():
    """关闭当前项目"""
    ProjectManager.close_project()
    return {"status": "closed"}


@router.post("/api/projects/history/pin")
def pin_project(req: ProjectPinRequest):
    try:
        metadata = ProjectManager.set_project_pinned(req.path, req.pinned)
        return {"status": "ok", "project": metadata}
    except ValueError as e:
        return {"error": str(e)}


@router.post("/api/projects/history/rename")
def rename_project_display(req: ProjectDisplayNameRequest):
    try:
        metadata = ProjectManager.rename_project_display(req.path, req.name)
        return {"status": "ok", "project": metadata}
    except ValueError as e:
        return {"error": str(e)}


@router.post("/api/projects/history/archive-sessions")
def archive_project_sessions(req: ProjectPathRequest):
    from app.agent import archive_session_records_for_project

    try:
        archived_count = archive_session_records_for_project(req.path, agent_type="coding")
        metadata = ProjectManager.get_project_history(req.path)
        return {"status": "ok", "archived_sessions": archived_count, "project": metadata}
    except ValueError as e:
        return {"error": str(e)}


@router.post("/api/projects/history/remove")
def remove_project_from_history(req: ProjectPathRequest):
    try:
        metadata = ProjectManager.remove_project_from_history(req.path)
        return {"status": "ok", "project": metadata}
    except ValueError as e:
        return {"error": str(e)}


@router.post("/api/projects/worktrees/persistent")
def create_persistent_worktree(req: PersistentWorktreeRequest):
    source_path = Path(req.path).expanduser().resolve()
    if not source_path.exists() or not source_path.is_dir():
        return {"error": f"Project path is not a directory: {req.path}"}

    code, root_text, stderr = _run_git(["rev-parse", "--show-toplevel"], source_path)
    if code != 0:
        return {"error": f"Project is not a Git repository: {stderr or req.path}"}
    root = Path(root_text.strip()).resolve()

    code, commit_text, stderr = _run_git(["rev-parse", "HEAD"], root)
    if code != 0 or not commit_text.strip():
        return {"error": f"Unable to read HEAD commit: {stderr or req.path}"}
    commit = commit_text.strip()

    default_name = f"{source_path.name}-worktree"
    slug = _slugify_worktree_name(req.name or default_name)
    parent = runtime_dir("worktrees") / "persistent" / _project_id(str(root))
    parent.mkdir(parents=True, exist_ok=True)
    target = _unique_worktree_target(parent, slug)

    code, _, stderr = _run_git(["worktree", "add", "--detach", str(target), commit], root, timeout=60)
    if code != 0:
        return {"error": f"Failed to create worktree: {stderr}"}

    try:
        project = ProjectManager.open_project(str(target.resolve()))
        CredentialManager.configure_gcm(str(target))
    except ValueError as e:
        return {"error": str(e)}

    return {
        "status": "ok",
        "path": str(target.resolve()),
        "base_project_path": str(root),
        "base_commit": commit,
        "project": project,
    }


@router.post("/api/projects/refresh")
def refresh_project():
    """Refresh current project metadata and file tree."""
    try:
        project = ProjectManager.refresh_current()
    except ValueError as e:
        return {"project": None, "nodes": [], "error": str(e)}
    if not project:
        return {"project": None, "nodes": [], "error": "No current project"}
    return {"project": project, "nodes": ProjectManager.get_tree()}


@router.post("/api/projects/create")
def create_project(req: CreateProjectRequest):
    """创建新项目"""
    try:
        return ProjectManager.create_project(req.parent_path, req.name, req.template)
    except ValueError as e:
        return {"error": str(e)}


@router.get("/api/projects/tree")
def get_project_tree(path: str = ""):
    """获取项目文件树"""
    return {"nodes": ProjectManager.get_tree(path)}


@router.post("/api/projects/fs/rename")
def rename_project_path(req: RenameProjectPathRequest):
    root, target, err = _resolve_project_target(req.path)
    if err or root is None or target is None:
        return {"error": err}
    if target == root:
        return {"error": "Cannot rename the project root"}
    if not target.exists():
        return {"error": f"Path does not exist: {req.path}"}

    name_err = _validate_child_name(req.new_name)
    if name_err:
        return {"error": name_err}

    destination = (target.parent / req.new_name.strip()).resolve()
    if not is_relative_to(destination, root):
        return {"error": "Destination escapes project"}
    if destination.exists():
        return {"error": f"Destination already exists: {req.new_name}"}

    try:
        target.rename(destination)
        project = ProjectManager.refresh_current()
    except OSError as e:
        return {"error": f"Rename failed: {e}"}

    return {
        "status": "ok",
        "path": _relative_project_path(root, target),
        "new_path": _relative_project_path(root, destination),
        "project": project,
    }


@router.post("/api/projects/fs/delete")
def delete_project_path(req: ProjectPathRequest):
    root, target, err = _resolve_project_target(req.path)
    if err or root is None or target is None:
        return {"error": err}
    if target == root:
        return {"error": "Cannot delete the project root"}
    if not target.exists():
        return {"error": f"Path does not exist: {req.path}"}

    try:
        _send_to_trash(target)
        project = ProjectManager.refresh_current()
    except OSError as e:
        return {"error": f"Delete failed: {e}"}
    except Exception as e:
        return {"error": f"Move to recycle bin failed: {e}"}

    return {
        "status": "ok",
        "path": _relative_project_path(root, target),
        "project": project,
    }


@router.post("/api/projects/actions/run")
async def run_project_action(req: ProjectRunRequest):
    root, target, err = _resolve_project_target(req.path)
    if err or root is None or target is None:
        return {"error": err}
    if not target.exists():
        return {"error": f"Path does not exist: {req.path}"}

    command, timeout, err = _build_run_command(root, target, req.action)
    if err or command is None:
        return {"error": err}

    result = await _run_project_command(command, root, timeout)
    return {
        "status": "ok" if not result.get("error") else "error",
        "path": _relative_project_path(root, target),
        "action": req.action,
        "cwd": str(root),
        "command": _command_display(command),
        **result,
    }


# ── Agent rules (.desktop-agent.md / AGENTS.md) ──────────────────────────

class RulesWriteRequest(BaseModel):
    model_config = {"protected_namespaces": ()}
    content: str


@router.get("/api/projects/rules")
def get_project_rules_endpoint():
    """读取当前项目的 .desktop-agent.md 规则文件。"""
    project = ProjectManager.get_current()
    if not project:
        return JSONResponse(
            status_code=400,
            content={"error": {"category": "validation", "message": "没有打开的项目"}},
        )
    rules_path = Path(project["path"]) / PROJECT_RULES_FILE
    exists = rules_path.exists()
    content = ""
    if exists:
        try:
            content = rules_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return {"error": {"category": "internal", "message": f"读取规则文件失败: {e}"}}
    return {"path": str(rules_path), "exists": exists, "content": content}


@router.put("/api/projects/rules")
def save_project_rules_endpoint(req: RulesWriteRequest):
    """保存当前项目的 .desktop-agent.md 规则文件。"""
    project = ProjectManager.get_current()
    if not project:
        return JSONResponse(
            status_code=400,
            content={"error": {"category": "validation", "message": "没有打开的项目"}},
        )
    rules_path = Path(project["path"]) / PROJECT_RULES_FILE
    try:
        rules_path.write_text(req.content, encoding="utf-8")
    except OSError as e:
        return JSONResponse(
            status_code=500,
            content={"error": {"category": "internal", "message": f"保存规则文件失败: {e}"}},
        )
    return {"status": "ok", "path": str(rules_path)}


@router.get("/api/projects/rules/user")
def get_user_rules_endpoint():
    """读取全局用户规则 ~/.desktop-agent/AGENTS.md。"""
    rules_path = Path.home() / USER_RULES_DIR / USER_RULES_FILE
    exists = rules_path.exists()
    content = ""
    if exists:
        try:
            content = rules_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return {"error": {"category": "internal", "message": f"读取用户规则失败: {e}"}}
    return {"path": str(rules_path), "exists": exists, "content": content}


@router.put("/api/projects/rules/user")
def save_user_rules_endpoint(req: RulesWriteRequest):
    """保存全局用户规则 ~/.desktop-agent/AGENTS.md。"""
    rules_dir = Path.home() / USER_RULES_DIR
    rules_path = rules_dir / USER_RULES_FILE
    try:
        rules_dir.mkdir(parents=True, exist_ok=True)
        rules_path.write_text(req.content, encoding="utf-8")
    except OSError as e:
        return JSONResponse(
            status_code=500,
            content={"error": {"category": "internal", "message": f"保存用户规则失败: {e}"}},
        )
    return {"status": "ok", "path": str(rules_path)}
