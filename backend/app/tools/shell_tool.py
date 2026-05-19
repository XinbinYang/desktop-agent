import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Optional
from app.tools.base import BaseTool, ToolResult
from app.security import is_relative_to

# 危险命令检测（模块级共享，供所有 shell 工具使用）
_DANGEROUS_COMMAND_PATTERNS = [
    r"rm\s+-rf\s+[/~]",
    r"del\s+/[fq]",
    r"(^|[;&|]\s*)format\s+[a-z]:",
    r"dd\s+if=",
    r">\s*/dev/sda",
    r"mkfs\.",
    r":\(\)\{\s*:\|:&\s*\};:",  # fork bomb
    r"shutdown\s+-[hrt]",
    r"rd\s+/s\s+/q",
    r"git\s+push\s+(--force|-f)\b",
    r"git\s+push\s+.*\s+(--force|-f)\b",
    r"git\s+reset\s+--hard\b",
    r"git\s+checkout\s+\.\s*$",
    r"git\s+checkout\s+--\s+\.",
    r"git\s+clean\s+-[fdx]+",
    r"git\s+branch\s+-[dD]\b",
]
_DANGEROUS_COMMAND_LITERALS = [
    "rm -rf /", "rm -rf ~", "rm -rf /*",
    "del /q /s /f c:\\", "format c:",
    "> /dev/sda", "dd if=/dev/zero of=/dev/sda",
    "git push --force", "git push -f",
    "git reset --hard",
    "git clean -fd", "git clean -fdx",
    "git branch -D",
]


def _is_dangerous_command(cmd: str) -> bool:
    """检查 shell 命令是否匹配已知的不可逆/危险模式"""
    lower = cmd.lower()
    if any(p.lower() in lower for p in _DANGEROUS_COMMAND_LITERALS):
        return True
    for pattern in _DANGEROUS_COMMAND_PATTERNS:
        if re.search(pattern, lower):
            return True
    return False


def _default_work_dir(agent_type: str = "") -> str:
    try:
        from app.coding_runs import get_run_context
        ctx = get_run_context()
        if ctx and ctx.active_path:
            return ctx.active_path
    except Exception:
        pass

    if agent_type == "personal":
        try:
            from app.runtime_paths import PERSONAL_WORKSPACE_DIRNAME, agents_dir
            home = agents_dir() / "personal" / PERSONAL_WORKSPACE_DIRNAME
            home.mkdir(parents=True, exist_ok=True)
            return str(home)
        except Exception:
            pass

    try:
        from app.coding_runs import effective_project_path
        bound = effective_project_path()
        if bound:
            return bound
    except Exception:
        pass

    return os.getcwd()


def _resolve_shell_cwd(cwd: str, agent_type: str = "") -> tuple[str, Optional[str]]:
    if not cwd:
        return _default_work_dir(agent_type), None

    if agent_type != "personal":
        return cwd, None

    try:
        from app.runtime_paths import PERSONAL_WORKSPACE_DIRNAME, agents_dir

        raw = Path(cwd).expanduser()
        parts = raw.parts
        if not raw.is_absolute() and parts and parts[0].lower() == "agents":
            rest = Path(*parts[1:]) if len(parts) > 1 else Path(".")
            resolved = (agents_dir() / rest).resolve()
        else:
            resolved = raw.resolve()

        agents_root = agents_dir().resolve()
        personal_root = agents_root / "personal"
        personal_workspace = personal_root / PERSONAL_WORKSPACE_DIRNAME
        shared_root = agents_root / "_shared"
        shared_workspace = shared_root / PERSONAL_WORKSPACE_DIRNAME

        protected_personal = is_relative_to(resolved, personal_root) and not is_relative_to(resolved, personal_workspace)
        protected_shared = is_relative_to(resolved, shared_root) and not is_relative_to(resolved, shared_workspace)
        if resolved == agents_root or protected_personal or protected_shared:
            return str(resolved), "Personal Agent shell cwd must be inside AGENTS/personal/WORKSPACE or an allowed project path."
        return str(resolved), None
    except (OSError, ValueError) as exc:
        return cwd, f"Invalid cwd: {cwd} ({exc})"


class ShellExecuteTool(BaseTool):
    name = "shell_execute"
    description = (
        "在本地终端执行命令。支持 Windows (cmd/powershell) 和 Linux/macOS (bash). "
        "危险命令（rm -rf, del /q 等）需要用户确认。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "cwd": {"type": "string", "description": "工作目录，默认为当前目录", "default": ""},
            "timeout": {"type": "integer", "description": "超时时间（秒）", "default": 60}
        },
        "required": ["command"]
    }

    async def execute(self, command: str, cwd: str = "", timeout: int = 60, agent_type: str = "") -> ToolResult:
        if _is_dangerous_command(command):
            return ToolResult(error=f"不可逆操作需用户确认: {command}。请在确认后重试，或让用户手动执行此命令。")
        
        work_dir, cwd_err = _resolve_shell_cwd(cwd, agent_type)
        if cwd_err:
            return ToolResult(error=cwd_err)
        
        # 根据系统选择 shell
        if os.name == "nt":
            # Windows
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                env=os.environ.copy()
            )
        else:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=work_dir,
                executable="/bin/bash"
            )
        
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            out_text = stdout.decode("utf-8", errors="ignore")[:10000]  # 截断
            err_text = stderr.decode("utf-8", errors="ignore")[:5000]
            
            if process.returncode != 0:
                return ToolResult(
                    output=out_text,
                    error=f"退出码 {process.returncode}: {err_text}"
                )
            return ToolResult(output=out_text or "（命令执行成功，无输出）")
        except asyncio.TimeoutError:
            process.kill()
            return ToolResult(error=f"命令执行超时（>{timeout}秒）")
        except OSError as e:
            return ToolResult(error=f"系统错误: {e}")

class ShellStartTool(BaseTool):
    name = "shell_start"
    description = "在后台启动一个程序（不等待其结束）。用于启动长期运行的服务或应用。"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要启动的命令"},
            "cwd": {"type": "string", "description": "工作目录", "default": ""}
        },
        "required": ["command"]
    }
    
    async def execute(self, command: str, cwd: str = "", agent_type: str = "") -> ToolResult:
        if _is_dangerous_command(command):
            return ToolResult(error=f"不可逆操作需用户确认: {command}。请在确认后重试，或让用户手动执行此命令。")
        work_dir, cwd_err = _resolve_shell_cwd(cwd, agent_type)
        if cwd_err:
            return ToolResult(error=cwd_err)
        try:
            if os.name == "nt":
                subprocess = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    cwd=work_dir,
                    creationflags=0x00000008  # DETACHED_PROCESS
                )
            else:
                subprocess = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    cwd=work_dir
                )
            return ToolResult(output=f"进程已启动，PID: {subprocess.pid}")
        except OSError as e:
            return ToolResult(error=f"系统错误: {e}")
