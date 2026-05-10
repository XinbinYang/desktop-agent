import asyncio
import os
import shutil
from typing import Optional
from app.tools.base import BaseTool, ToolResult

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
    
    # 危险命令关键字（正则模式 + 固定字符串）
    DANGEROUS_PATTERNS = [
        r"rm\s+-rf\s+[/~]",
        r"del\s+/[fq]",
        r"format\s+",
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
    DANGEROUS_LITERALS = [
        "rm -rf /", "rm -rf ~", "rm -rf /*",
        "del /q /s /f c:\\", "format c:",
        "> /dev/sda", "dd if=/dev/zero of=/dev/sda",
        "git push --force", "git push -f",
        "git reset --hard",
        "git clean -fd", "git clean -fdx",
        "git branch -D",
    ]

    def _is_dangerous(self, cmd: str) -> bool:
        import re
        lower = cmd.lower()
        if any(p.lower() in lower for p in self.DANGEROUS_LITERALS):
            return True
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, lower):
                return True
        return False
    
    async def execute(self, command: str, cwd: str = "", timeout: int = 60) -> ToolResult:
        if self._is_dangerous(command):
            return ToolResult(error=f"不可逆操作需用户确认: {command}。请在确认后重试，或让用户手动执行此命令。")
        
        work_dir = cwd if cwd else os.getcwd()
        
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
    
    async def execute(self, command: str, cwd: str = "") -> ToolResult:
        work_dir = cwd if cwd else os.getcwd()
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