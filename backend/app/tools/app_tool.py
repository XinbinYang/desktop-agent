import os
import subprocess
import asyncio
import shlex
from typing import Optional
from app.tools.base import BaseTool, ToolResult

try:
    import pywinauto
    from pywinauto import Desktop
    HAS_PYWINAUTO = True
except Exception:
    HAS_PYWINAUTO = False

class AppOpenTool(BaseTool):
    name = "app_open"
    description = "启动指定的应用程序。支持可执行文件路径或系统命令（如 notepad, calc, code）。"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "程序路径或命令"},
            "args": {"type": "string", "description": "启动参数", "default": ""},
            "wait": {"type": "boolean", "description": "是否等待窗口出现", "default": False}
        },
        "required": ["command"]
    }
    
    async def execute(self, command: str, args: str = "", wait: bool = False) -> ToolResult:
        try:
            cmd_list = [command]
            if args:
                cmd_list.extend(shlex.split(args))
            
            proc = subprocess.Popen(
                cmd_list,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            if wait and HAS_PYWINAUTO:
                await asyncio.sleep(2)
                return ToolResult(output=f"程序已启动，PID: {proc.pid}（等待窗口模式）")
            
            return ToolResult(output=f"程序已启动，PID: {proc.pid}")
        except OSError as e:
            return ToolResult(error=f"应用操作错误: {e}")

class AppListWindowsTool(BaseTool):
    name = "app_list_windows"
    description = "列出当前所有可见窗口的标题（Windows 专用）。"
    parameters = {"type": "object", "properties": {}, "required": []}
    
    async def execute(self) -> ToolResult:
        if not HAS_PYWINAUTO:
            return ToolResult(error="pywinauto 未安装或不在 Windows 系统")
        try:
            windows = Desktop(backend="uia").windows()
            titles = [w.window_text() for w in windows if w.window_text()]
            output = "\n".join([f"- {t}" for t in titles[:50]])  # 限制数量
            return ToolResult(output=output or "未找到可见窗口")
        except OSError as e:
            return ToolResult(error=f"应用操作错误: {e}")

class AppFindWindowTool(BaseTool):
    name = "app_find_window"
    description = "根据窗口标题关键字查找窗口，返回窗口信息。"
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "窗口标题关键字"}
        },
        "required": ["title"]
    }
    
    async def execute(self, title: str) -> ToolResult:
        if not HAS_PYWINAUTO:
            return ToolResult(error="pywinauto 未安装或不在 Windows 系统")
        try:
            desktop = Desktop(backend="uia")
            matches = []
            for w in desktop.windows():
                if title.lower() in w.window_text().lower():
                    rect = w.rectangle()
                    matches.append(
                        f"标题: {w.window_text()}, "
                        f"位置: ({rect.left}, {rect.top}, {rect.right}, {rect.bottom}), "
                        f"句柄: {w.handle}"
                    )
            return ToolResult(output="\n".join(matches) if matches else "未找到匹配窗口")
        except OSError as e:
            return ToolResult(error=f"应用操作错误: {e}")

class AppClickTool(BaseTool):
    name = "app_click"
    description = "在指定窗口内点击 UI 元素（通过名称）。需要窗口标题和元素名称。"
    parameters = {
        "type": "object",
        "properties": {
            "window_title": {"type": "string", "description": "窗口标题关键字"},
            "element_name": {"type": "string", "description": "UI 元素名称（如 '确定', 'File'）"}
        },
        "required": ["window_title", "element_name"]
    }
    
    async def execute(self, window_title: str, element_name: str) -> ToolResult:
        if not HAS_PYWINAUTO:
            return ToolResult(error="pywinauto 未安装或不在 Windows 系统")
        try:
            from pywinauto.findwindows import find_windows
            handles = find_windows(title_re=f".*{window_title}.*")
            if not handles:
                return ToolResult(error=f"未找到窗口: {window_title}")
            
            app = pywinauto.Application(backend="uia").connect(handle=handles[0])
            dlg = app.window(handle=handles[0])
            dlg.child_window(title_re=f".*{element_name}.*").click_input()
            return ToolResult(output=f"已在窗口 '{window_title}' 中点击 '{element_name}'")
        except OSError as e:
            return ToolResult(error=f"应用操作错误: {e}")

class AppTypeTool(BaseTool):
    name = "app_type"
    description = "在指定窗口的编辑框中输入文字。"
    parameters = {
        "type": "object",
        "properties": {
            "window_title": {"type": "string", "description": "窗口标题关键字"},
            "text": {"type": "string", "description": "要输入的文字"}
        },
        "required": ["window_title", "text"]
    }
    
    async def execute(self, window_title: str, text: str) -> ToolResult:
        if not HAS_PYWINAUTO:
            return ToolResult(error="pywinauto 未安装或不在 Windows 系统")
        try:
            from pywinauto.findwindows import find_windows
            handles = find_windows(title_re=f".*{window_title}.*")
            if not handles:
                return ToolResult(error=f"未找到窗口: {window_title}")
            
            app = pywinauto.Application(backend="uia").connect(handle=handles[0])
            dlg = app.window(handle=handles[0])
            dlg.type_keys(text, with_spaces=True)
            return ToolResult(output=f"已在窗口 '{window_title}' 中输入文字")
        except OSError as e:
            return ToolResult(error=f"应用操作错误: {e}")