import os
import aiofiles
from pathlib import Path
from typing import Any, Dict
from app.tools.base import BaseTool, ToolResult

class FileReadTool(BaseTool):
    name = "file_read"
    description = "读取本地文件内容。支持文本文件，对大文件会自动截断。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件的绝对路径"},
            "offset": {"type": "integer", "description": "起始行号，从0开始", "default": 0},
            "limit": {"type": "integer", "description": "读取最大行数", "default": 200}
        },
        "required": ["path"]
    }
    
    async def execute(self, path: str, offset: int = 0, limit: int = 200) -> ToolResult:
        try:
            p = Path(path).resolve()
            if not p.exists():
                return ToolResult(error=f"文件不存在: {path}")
            if not p.is_file():
                return ToolResult(error=f"路径不是文件: {path}")
            
            # 安全限制：避免读取超大文件
            size = p.stat().st_size
            if size > 10 * 1024 * 1024:  # 10MB
                return ToolResult(error=f"文件过大 ({size} bytes)，拒绝读取")
            
            async with aiofiles.open(p, "r", encoding="utf-8", errors="ignore") as f:
                lines = await f.readlines()
            
            selected = lines[offset:offset+limit]
            content = "".join(selected)
            info = f"\n\n[文件: {p}, 共 {len(lines)} 行, 显示 {offset}-{offset+len(selected)}]"
            return ToolResult(output=content + info)
        except OSError as e:
            return ToolResult(error=f"文件操作错误: {e}")

class FileWriteTool(BaseTool):
    name = "file_write"
    description = "写入或覆盖文件内容。如果目录不存在会自动创建。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件的绝对路径"},
            "content": {"type": "string", "description": "要写入的内容"}
        },
        "required": ["path", "content"]
    }
    
    async def execute(self, path: str, content: str) -> ToolResult:
        try:
            p = Path(path).resolve()
            p.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(p, "w", encoding="utf-8") as f:
                await f.write(content)
            return ToolResult(output=f"文件已写入: {p}")
        except OSError as e:
            return ToolResult(error=f"文件操作错误: {e}")

class FileListTool(BaseTool):
    name = "file_list"
    description = "列出指定目录下的文件和文件夹。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目录的绝对路径，默认为当前工作目录"},
            "recursive": {"type": "boolean", "description": "是否递归列出", "default": False}
        },
        "required": ["path"]
    }
    
    async def execute(self, path: str, recursive: bool = False) -> ToolResult:
        try:
            p = Path(path).resolve()
            if not p.exists():
                return ToolResult(error=f"目录不存在: {path}")
            
            lines = []
            if recursive:
                for item in p.rglob("*"):
                    rel = item.relative_to(p)
                    marker = "📁" if item.is_dir() else "📄"
                    lines.append(f"{marker} {rel}")
            else:
                for item in p.iterdir():
                    marker = "📁" if item.is_dir() else "📄"
                    lines.append(f"{marker} {item.name}")
            
            return ToolResult(output="\n".join(lines) if lines else "（空目录）")
        except OSError as e:
            return ToolResult(error=f"文件操作错误: {e}")

class FileSearchTool(BaseTool):
    name = "file_search"
    description = "在指定目录下搜索文件名包含关键字的文件。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "搜索根目录"},
            "keyword": {"type": "string", "description": "文件名关键字"}
        },
        "required": ["path", "keyword"]
    }
    
    async def execute(self, path: str, keyword: str) -> ToolResult:
        try:
            p = Path(path).resolve()
            matches = []
            for item in p.rglob(f"*{keyword}*"):
                matches.append(str(item.relative_to(p)))
            return ToolResult(output="\n".join(matches) if matches else "未找到匹配文件")
        except OSError as e:
            return ToolResult(error=f"文件操作错误: {e}")

class FileDeleteTool(BaseTool):
    name = "file_delete"
    description = "删除指定文件。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要删除的文件路径"}
        },
        "required": ["path"]
    }
    
    async def execute(self, path: str) -> ToolResult:
        try:
            p = Path(path).resolve()
            if p.is_file():
                p.unlink()
                return ToolResult(output=f"已删除: {p}")
            else:
                return ToolResult(error=f"不是文件或不存在: {path}")
        except OSError as e:
            return ToolResult(error=f"文件操作错误: {e}")