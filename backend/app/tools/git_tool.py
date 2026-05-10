import base64
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from app.tools.base import BaseTool, ToolResult
from app.project_manager import ProjectManager
from app.credential_manager import CredentialManager
from app.security import redact_sensitive_text


def _run_git(args: List[str], cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None,
             timeout: int = 30) -> Tuple[int, str, str]:
    """运行 git 命令，返回 (returncode, stdout, stderr)"""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env
        )
        return result.returncode, redact_sensitive_text(result.stdout), redact_sensitive_text(result.stderr)
    except subprocess.TimeoutExpired:
        return 1, "", f"git command timed out after {timeout}s"
    except FileNotFoundError:
        return 1, "", "git command not found. Please install Git."
    except OSError as e:
        return 1, "", str(e)


def _basic_auth_env(username: str, token: str) -> Dict[str, str]:
    """Build env vars that inject `http.extraheader: Authorization: Basic ...`.

    Uses git's GIT_CONFIG_COUNT / GIT_CONFIG_KEY_N / GIT_CONFIG_VALUE_N
    protocol (git >= 2.31) so the credential is not visible on the process
    command line — unlike `-c http.extraheader=...` which leaks via ps/Task
    Manager. Multiple call sites can merge their dicts via ``env.update()``.
    """
    raw = f"{username}:{token}".encode("utf-8")
    encoded = base64.b64encode(raw).decode("ascii")
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraheader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {encoded}",
    }


def _auth_env_for_remote(remote_url: str) -> Dict[str, str]:
    if not remote_url.startswith(("https://", "http://")):
        return {}
    creds = CredentialManager.get_git_credentials(remote_url)
    if not creds:
        return {}
    username, token = creds
    if not username or not token:
        return {}
    return _basic_auth_env(username, token)


def _get_project_cwd() -> Optional[str]:
    """获取当前项目的目录路径"""
    project = ProjectManager.get_current()
    if project:
        return project.get("path")
    return None


def _ensure_project() -> Tuple[Optional[str], Optional[str]]:
    """确保有当前项目，返回 (cwd, error)"""
    cwd = _get_project_cwd()
    if not cwd:
        return None, "No project is currently open. Use 'open_project' first."
    return cwd, None


class GitCloneTool(BaseTool):
    name = "git_clone"
    description = "Clone a Git repository into a new directory."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The repository URL to clone"},
            "path": {"type": "string", "description": "Optional: target directory path. Defaults to current project or a new folder named after the repo"},
            "token": {"type": "string", "description": "Optional: personal access token for private repos. Will be stored via GCM for future use."}
        },
        "required": ["url"]
    }

    async def execute(self, url: str, path: Optional[str] = None, token: Optional[str] = None) -> ToolResult:  # type: ignore[override]
        if path:
            target = Path(path).resolve()
        else:
            # 从 URL 提取 repo 名
            repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
            project = ProjectManager.get_current()
            if project:
                target = Path(project["path"]).parent / repo_name
            else:
                target = Path.cwd() / repo_name

        target = target.resolve()

        clone_url = url
        env: Optional[Dict[str, str]] = None
        if token and url.startswith("https://"):
            rest = url[len("https://"):]
            host = rest.split("/")[0] if "/" in rest else rest
            CredentialManager.gcm_approve("https", host, "oauth2", token)
            CredentialManager.store_token(host, "oauth2", token)
            env = os.environ.copy()
            env.update(_basic_auth_env("oauth2", token))

        code, stdout, stderr = _run_git(["clone", clone_url, str(target)], env=env, timeout=120)
        if code != 0:
            return ToolResult(error=f"Git clone failed: {stderr}")

        return ToolResult(output=f"Repository cloned to {target}")


class GitStatusTool(BaseTool):
    name = "git_status"
    description = "Show the working tree status: branch, modified files, untracked files, ahead/behind counts."
    parameters = {
        "type": "object",
        "properties": {},
    }

    async def execute(self) -> ToolResult:
        cwd, err = _ensure_project()
        if err:
            return ToolResult(error=err)

        # Branch
        code, branch, _ = _run_git(["branch", "--show-current"], cwd=cwd)
        branch = branch.strip() if code == 0 else "unknown"

        # Short status
        code, status_out, _ = _run_git(["status", "--short"], cwd=cwd)

        modified = []
        untracked = []
        staged = []
        if code == 0:
            for line in status_out.strip().split("\n"):
                if not line:
                    continue
                st = line[:2]
                filepath = line[3:]
                if st.startswith("??"):
                    untracked.append(filepath)
                else:
                    if st[0] != " ":
                        staged.append(filepath)
                    if st[1] != " ":
                        modified.append(filepath)

        # Ahead/behind
        ahead, behind = 0, 0
        code, ab, _ = _run_git(
            ["rev-list", "--left-right", "--count", f"origin/{branch}...{branch}"],
            cwd=cwd
        )
        if code == 0:
            parts = ab.strip().split("\t")
            if len(parts) == 2:
                behind = int(parts[0])
                ahead = int(parts[1])

        result = {
            "branch": branch,
            "ahead": ahead,
            "behind": behind,
            "modified": modified,
            "untracked": untracked,
            "staged": staged,
        }
        return ToolResult(output=str(result))


class GitDiffTool(BaseTool):
    name = "git_diff"
    description = "Show git diff for the current project, optionally scoped to a path or staged changes."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Optional path to diff"},
            "staged": {"type": "boolean", "description": "Show staged changes instead of working tree changes", "default": False},
            "include_untracked": {"type": "boolean", "description": "List untracked files when showing working tree diff", "default": True},
        },
    }

    async def execute(
        self,
        path: Optional[str] = None,
        staged: bool = False,
        include_untracked: bool = True,
    ) -> ToolResult:
        cwd, err = _ensure_project()
        if err:
            return ToolResult(error=err)

        args = ["diff"]
        if staged:
            args.append("--staged")
        if path:
            args.extend(["--", path])

        code, stdout, stderr = _run_git(args, cwd=cwd)
        if code != 0:
            return ToolResult(error=f"Git diff failed: {stderr}")

        parts = [stdout.strip()] if stdout.strip() else []
        if include_untracked and not staged:
            untracked_args = ["ls-files", "--others", "--exclude-standard"]
            if path:
                untracked_args.extend(["--", path])
            code, untracked, stderr = _run_git(untracked_args, cwd=cwd)
            if code != 0:
                return ToolResult(error=f"Git untracked listing failed: {stderr}")
            if untracked.strip():
                parts.append("[Untracked files]\n" + untracked.strip())

        return ToolResult(output="\n\n".join(parts) if parts else "(no diff)")


class GitCommitTool(BaseTool):
    name = "git_commit"
    description = "Record changes to the repository with a commit message."
    parameters = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "The commit message"},
            "files": {"type": "array", "items": {"type": "string"}, "description": "Optional: specific files to stage. If omitted, stages all changes."}
        },
        "required": ["message"]
    }

    async def execute(self, message: str, files: Optional[List[str]] = None) -> ToolResult:
        cwd, err = _ensure_project()
        if err:
            return ToolResult(error=err)

        if files:
            for f in files:
                _run_git(["add", f], cwd=cwd)
        else:
            _run_git(["add", "-A"], cwd=cwd)

        code, stdout, stderr = _run_git(["commit", "-m", message], cwd=cwd)
        if code != 0:
            return ToolResult(error=f"Git commit failed: {stderr}")
        return ToolResult(output=f"Committed: {message}")


class GitPullTool(BaseTool):
    name = "git_pull"
    description = "Fetch from and integrate with another repository or a local branch."
    parameters = {
        "type": "object",
        "properties": {
            "remote": {"type": "string", "description": "Remote name", "default": "origin"},
            "branch": {"type": "string", "description": "Branch name. Defaults to current branch."}
        }
    }

    async def execute(self, remote: str = "origin", branch: Optional[str] = None) -> ToolResult:
        cwd, err = _ensure_project()
        if err:
            return ToolResult(error=err)

        code, remote_url, _ = _run_git(["remote", "get-url", remote], cwd=cwd)
        remote_url = remote_url.strip() if code == 0 else ""

        env = os.environ.copy()
        env.update(_auth_env_for_remote(remote_url))

        args = ["pull", remote]
        if branch:
            args.append(branch)

        code, stdout, stderr = _run_git(args, cwd=cwd, env=env, timeout=60)
        if code != 0:
            return ToolResult(error=f"Git pull failed: {stderr}")
        return ToolResult(output=f"Pulled successfully.\n{stdout}")


class GitPushTool(BaseTool):
    name = "git_push"
    description = "Update remote refs along with associated objects. Use 'force' for force-push (requires unrestricted sandbox)."
    parameters = {
        "type": "object",
        "properties": {
            "remote": {"type": "string", "description": "Remote name", "default": "origin"},
            "branch": {"type": "string", "description": "Branch name. Defaults to current branch."},
            "force": {"type": "boolean", "description": "Force push (--force). Only allowed when sandbox_mode is unrestricted.", "default": False}
        }
    }

    async def execute(self, remote: str = "origin", branch: Optional[str] = None, force: bool = False) -> ToolResult:
        from app.config import load_config
        if force and load_config().settings.sandbox_mode != "unrestricted":
            return ToolResult(error=f"不可逆操作需用户确认: git push --force。请在后端设置中启用 unrestricted sandbox 模式，或让用户手动执行此命令。")

        cwd, err = _ensure_project()
        if err:
            return ToolResult(error=err)

        code, remote_url, _ = _run_git(["remote", "get-url", remote], cwd=cwd)
        remote_url = remote_url.strip() if code == 0 else ""

        env = os.environ.copy()
        env.update(_auth_env_for_remote(remote_url))

        args = ["push", remote]
        if branch:
            args.append(branch)
        if force:
            args.append("--force")

        code, stdout, stderr = _run_git(args, cwd=cwd, env=env, timeout=60)
        if code != 0:
            return ToolResult(error=f"Git push failed: {stderr}")
        return ToolResult(output=f"Pushed successfully.\n{stdout}")


class GitBranchTool(BaseTool):
    name = "git_branch"
    description = "List, create, or delete branches."
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "create", "delete", "switch"], "description": "Action to perform"},
            "name": {"type": "string", "description": "Branch name (required for create/delete/switch)"}
        },
        "required": ["action"]
    }

    async def execute(self, action: str, name: Optional[str] = None) -> ToolResult:
        cwd, err = _ensure_project()
        if err:
            return ToolResult(error=err)

        if action == "list":
            code, stdout, stderr = _run_git(["branch", "-a"], cwd=cwd)
            if code != 0:
                return ToolResult(error=f"Git branch failed: {stderr}")
            return ToolResult(output=stdout)

        if not name:
            return ToolResult(error="Branch name is required for create/delete/switch actions")

        if action == "create":
            code, _, stderr = _run_git(["checkout", "-b", name], cwd=cwd)
        elif action == "delete":
            code, _, stderr = _run_git(["branch", "-D", name], cwd=cwd)
        elif action == "switch":
            code, _, stderr = _run_git(["checkout", name], cwd=cwd)
        else:
            return ToolResult(error=f"Unknown action: {action}")

        if code != 0:
            return ToolResult(error=f"Git branch {action} failed: {stderr}")
        return ToolResult(output=f"Branch {action}: {name}")


class GitRemoteTool(BaseTool):
    name = "git_remote"
    description = "Manage set of tracked repositories."
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "add", "remove"], "description": "Action to perform"},
            "name": {"type": "string", "description": "Remote name"},
            "url": {"type": "string", "description": "Remote URL (required for add)"}
        },
        "required": ["action"]
    }

    async def execute(self, action: str, name: Optional[str] = None, url: Optional[str] = None) -> ToolResult:
        cwd, err = _ensure_project()
        if err:
            return ToolResult(error=err)

        if action == "list":
            code, stdout, stderr = _run_git(["remote", "-v"], cwd=cwd)
            if code != 0:
                return ToolResult(error=f"Git remote failed: {stderr}")
            return ToolResult(output=stdout or "No remotes configured")

        if action == "add":
            if not name or not url:
                return ToolResult(error="Both name and url are required for add")
            code, _, stderr = _run_git(["remote", "add", name, url], cwd=cwd)
            if code != 0:
                return ToolResult(error=f"Git remote add failed: {stderr}")
            return ToolResult(output=f"Remote added: {name} -> {url}")

        if action == "remove":
            if not name:
                return ToolResult(error="Name is required for remove")
            code, _, stderr = _run_git(["remote", "remove", name], cwd=cwd)
            if code != 0:
                return ToolResult(error=f"Git remote remove failed: {stderr}")
            return ToolResult(output=f"Remote removed: {name}")

        return ToolResult(error=f"Unknown action: {action}")
