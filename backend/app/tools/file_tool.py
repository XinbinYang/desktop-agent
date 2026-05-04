import os
import aiofiles
from pathlib import Path
from typing import Any, Dict, Optional
from app.tools.base import BaseTool, ToolResult
from app.project_manager import ProjectManager
from app.security import resolve_under_base

# æ–‡ä»¶æ“ä½œæ²™ç®±ï¼šé™åˆ¶åœ¨é¡¹ç›®æ ¹ç›®å½•å†…
_PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()


def _get_base_path(project_relative: bool = False) -> Path:
    """èŽ·å–æ–‡ä»¶æ“ä½œçš„åŸºç¡€è·¯å¾„"""
    if project_relative:
        project = ProjectManager.get_current()
        if project:
            return Path(project["path"]).resolve()
    return _PROJECT_ROOT


def _validate_path(path: str, project_relative: bool = False) -> tuple[Path, Optional[str]]:
    """éªŒè¯è·¯å¾„æ˜¯å¦åœ¨æ²™ç®±å†…ã€‚è¿”å›ž (resolved_path, error_message)ã€‚"""
    base = _get_base_path(project_relative)
    p, err = resolve_under_base(path, base, allow_relative=project_relative)
    if err:
        scope = "current project" if project_relative else "backend root"
        return p, f"路径越界: {err}. Only {scope} files under {base} are allowed."
    return p, None

class FileReadTool(BaseTool):
    name = "file_read"
    description = "è¯»å–æœ¬åœ°æ–‡ä»¶å†…å®¹ã€‚æ”¯æŒæ–‡æœ¬æ–‡ä»¶ï¼Œå¯¹å¤§æ–‡ä»¶ä¼šè‡ªåŠ¨æˆªæ–­ã€‚å½“ project_relative=true æ—¶ï¼Œpath ç›¸å¯¹äºŽå½“å‰æ‰“å¼€çš„é¡¹ç›®ç›®å½•è§£æžã€‚"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "æ–‡ä»¶è·¯å¾„ã€‚ç»å¯¹è·¯å¾„æˆ–ç›¸å¯¹äºŽé¡¹ç›®çš„ç›¸å¯¹è·¯å¾„ï¼ˆå½“ project_relative=true æ—¶ï¼‰"},
            "offset": {"type": "integer", "description": "èµ·å§‹è¡Œå·ï¼Œä»Ž0å¼€å§‹", "default": 0},
            "limit": {"type": "integer", "description": "è¯»å–æœ€å¤§è¡Œæ•°", "default": 200},
            "project_relative": {"type": "boolean", "description": "æ˜¯å¦å°†è·¯å¾„è§£æžä¸ºç›¸å¯¹äºŽå½“å‰é¡¹ç›®ç›®å½•", "default": False}
        },
        "required": ["path"]
    }
    
    async def execute(self, path: str, offset: int = 0, limit: int = 200, project_relative: bool = False) -> ToolResult:
        p, err = _validate_path(path, project_relative)
        if err:
            return ToolResult(error=err)
        try:
            if not p.exists():
                return ToolResult(error=f"文件不存在: {path}")
            if not p.is_file():
                return ToolResult(error=f"路径不是文件: {path}")
            
            # å®‰å…¨é™åˆ¶ï¼šé¿å…è¯»å–è¶…å¤§æ–‡ä»¶
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
    description = "å†™å…¥æˆ–è¦†ç›–æ–‡ä»¶å†…å®¹ã€‚å¦‚æžœç›®å½•ä¸å­˜åœ¨ä¼šè‡ªåŠ¨åˆ›å»ºã€‚å½“ project_relative=true æ—¶ï¼Œpath ç›¸å¯¹äºŽå½“å‰æ‰“å¼€çš„é¡¹ç›®ç›®å½•è§£æžã€‚"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "æ–‡ä»¶è·¯å¾„ã€‚ç»å¯¹è·¯å¾„æˆ–ç›¸å¯¹äºŽé¡¹ç›®çš„ç›¸å¯¹è·¯å¾„ï¼ˆå½“ project_relative=true æ—¶ï¼‰"},
            "content": {"type": "string", "description": "è¦å†™å…¥çš„å†…å®¹"},
            "project_relative": {"type": "boolean", "description": "æ˜¯å¦å°†è·¯å¾„è§£æžä¸ºç›¸å¯¹äºŽå½“å‰é¡¹ç›®ç›®å½•", "default": False}
        },
        "required": ["path", "content"]
    }
    
    async def execute(self, path: str, content: str, project_relative: bool = False) -> ToolResult:
        p, err = _validate_path(path, project_relative)
        if err:
            return ToolResult(error=err)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(p, "w", encoding="utf-8") as f:
                await f.write(content)
            return ToolResult(output=f"文件已写入: {p}")
        except OSError as e:
            return ToolResult(error=f"文件操作错误: {e}")

class FileListTool(BaseTool):
    name = "file_list"
    description = "åˆ—å‡ºæŒ‡å®šç›®å½•ä¸‹çš„æ–‡ä»¶å’Œæ–‡ä»¶å¤¹ã€‚å½“ project_relative=true æ—¶ï¼Œpath ç›¸å¯¹äºŽå½“å‰æ‰“å¼€çš„é¡¹ç›®ç›®å½•è§£æžã€‚"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "ç›®å½•è·¯å¾„ã€‚ç»å¯¹è·¯å¾„æˆ–ç›¸å¯¹äºŽé¡¹ç›®çš„ç›¸å¯¹è·¯å¾„ï¼ˆå½“ project_relative=true æ—¶ï¼‰"},
            "recursive": {"type": "boolean", "description": "æ˜¯å¦é€’å½’åˆ—å‡º", "default": False},
            "project_relative": {"type": "boolean", "description": "æ˜¯å¦å°†è·¯å¾„è§£æžä¸ºç›¸å¯¹äºŽå½“å‰é¡¹ç›®ç›®å½•", "default": False}
        },
        "required": ["path"]
    }
    
    async def execute(self, path: str, recursive: bool = False, project_relative: bool = False) -> ToolResult:
        p, err = _validate_path(path, project_relative)
        if err:
            return ToolResult(error=err)
        try:
            if not p.exists():
                return ToolResult(error=f"目录不存在: {path}")
            
            lines = []
            if recursive:
                for item in p.rglob("*"):
                    rel = item.relative_to(p)
                    marker = "ðŸ“" if item.is_dir() else "ðŸ“„"
                    lines.append(f"{marker} {rel}")
            else:
                for item in p.iterdir():
                    marker = "ðŸ“" if item.is_dir() else "ðŸ“„"
                    lines.append(f"{marker} {item.name}")
            
            return ToolResult(output="\n".join(lines) if lines else "（空目录）")
        except OSError as e:
            return ToolResult(error=f"文件操作错误: {e}")

class FileSearchTool(BaseTool):
    name = "file_search"
    description = "åœ¨æŒ‡å®šç›®å½•ä¸‹æœç´¢æ–‡ä»¶ååŒ…å«å…³é”®å­—çš„æ–‡ä»¶ã€‚å½“ project_relative=true æ—¶ï¼Œpath ç›¸å¯¹äºŽå½“å‰æ‰“å¼€çš„é¡¹ç›®ç›®å½•è§£æžã€‚"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "æœç´¢æ ¹ç›®å½•è·¯å¾„ã€‚ç»å¯¹è·¯å¾„æˆ–ç›¸å¯¹äºŽé¡¹ç›®çš„ç›¸å¯¹è·¯å¾„ï¼ˆå½“ project_relative=true æ—¶ï¼‰"},
            "keyword": {"type": "string", "description": "æ–‡ä»¶åå…³é”®å­—"},
            "project_relative": {"type": "boolean", "description": "æ˜¯å¦å°†è·¯å¾„è§£æžä¸ºç›¸å¯¹äºŽå½“å‰é¡¹ç›®ç›®å½•", "default": False}
        },
        "required": ["path", "keyword"]
    }
    
    async def execute(self, path: str, keyword: str, project_relative: bool = False) -> ToolResult:
        p, err = _validate_path(path, project_relative)
        if err:
            return ToolResult(error=err)
        try:
            matches = []
            for item in p.rglob(f"*{keyword}*"):
                matches.append(str(item.relative_to(p)))
            return ToolResult(output="\n".join(matches) if matches else "未找到匹配文件")
        except OSError as e:
            return ToolResult(error=f"文件操作错误: {e}")

class FileDeleteTool(BaseTool):
    name = "file_delete"
    description = "åˆ é™¤æŒ‡å®šæ–‡ä»¶ã€‚å½“ project_relative=true æ—¶ï¼Œpath ç›¸å¯¹äºŽå½“å‰æ‰“å¼€çš„é¡¹ç›®ç›®å½•è§£æžã€‚"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "è¦åˆ é™¤çš„æ–‡ä»¶è·¯å¾„ã€‚ç»å¯¹è·¯å¾„æˆ–ç›¸å¯¹äºŽé¡¹ç›®çš„ç›¸å¯¹è·¯å¾„ï¼ˆå½“ project_relative=true æ—¶ï¼‰"},
            "project_relative": {"type": "boolean", "description": "æ˜¯å¦å°†è·¯å¾„è§£æžä¸ºç›¸å¯¹äºŽå½“å‰é¡¹ç›®ç›®å½•", "default": False}
        },
        "required": ["path"]
    }
    
    async def execute(self, path: str, project_relative: bool = False) -> ToolResult:
        p, err = _validate_path(path, project_relative)
        if err:
            return ToolResult(error=err)
        try:
            if p.is_file():
                p.unlink()
                return ToolResult(output=f"已删除: {p}")
            else:
                return ToolResult(error=f"不是文件或不存在: {path}")
        except OSError as e:
            return ToolResult(error=f"文件操作错误: {e}")
