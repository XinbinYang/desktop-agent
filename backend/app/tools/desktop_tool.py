import base64
import io
import os
from typing import Optional
from PIL import Image
from app.tools.base import BaseTool, ToolResult

# 导入平台相关的库
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    HAS_PYAUTOGUI = True
except Exception:
    HAS_PYAUTOGUI = False

try:
    from pynput.keyboard import Controller as KeyboardController, Key
    HAS_PYNPUT = True
except Exception:
    HAS_PYNPUT = False

class ScreenshotTool(BaseTool):
    name = "screenshot"
    description = (
        "截取整个屏幕或指定区域的截图，返回 base64 编码的 PNG 图片。"
        "用于让 AI '看见' 当前屏幕状态。"
        "设置 annotate=true 可在截图上标注 OCR 识别到的文字元素（调试用）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "region": {
                "type": "array",
                "description": "截取区域 [left, top, width, height]，不传则全屏",
                "items": {"type": "integer"}
            },
            "annotate": {
                "type": "boolean",
                "description": "是否在截图上标注 OCR 识别到的 UI 元素（默认 false）",
            },
        },
        "required": []
    }
    
    async def execute(
        self,
        region: Optional[list] = None,
        annotate: bool = False,
        x: int = 0,
        y: int = 0,
        width: int = 0,
        height: int = 0,
    ) -> ToolResult:
        if not HAS_PYAUTOGUI:
            return ToolResult(error="pyautogui 未安装，无法截图")
        try:
            if x and width and height:
                img = pyautogui.screenshot(region=(x, y, width, height))
            elif region and len(region) == 4:
                img = pyautogui.screenshot(region=tuple(region))
            else:
                img = pyautogui.screenshot()

            # 压缩以节省 token
            img = img.convert("RGB")
            max_size = (1280, 720)
            img.thumbnail(max_size, Image.Resampling.LANCZOS)

            # Annotate with OCR results if requested
            if annotate:
                try:
                    from app.ocr import get_ocr_engine
                    import io as _io
                    buf = _io.BytesIO()
                    img.save(buf, format="PNG")
                    engine = get_ocr_engine()
                    results = engine.recognize(buf.getvalue())
                    if results:
                        from PIL import ImageDraw, ImageFont
                        draw = ImageDraw.Draw(img)
                        for r in results[:30]:
                            draw.rectangle(
                                [r.x, r.y, r.x + r.width, r.y + r.height],
                                outline="red", width=1,
                            )
                        img = img.copy()  # ensure draw is committed
                except Exception:
                    pass  # Annotation is best-effort, don't fail the screenshot

            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
            return ToolResult(output=f"截图已捕获，尺寸: {img.size}", base64_image=b64)
        except OSError as e:
            return ToolResult(error=f"桌面操作错误: {e}")

class MouseClickTool(BaseTool):
    name = "mouse_click"
    description = (
        "在屏幕指定坐标点击鼠标。坐标系原点在屏幕左上角。"
        "设置 relative=true 可将坐标视为相对于当前鼠标位置的偏移量。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "横坐标（或相对偏移量）"},
            "y": {"type": "integer", "description": "纵坐标（或相对偏移量）"},
            "button": {"type": "string", "description": "鼠标按键: left/right/middle", "default": "left"},
            "clicks": {"type": "integer", "description": "点击次数", "default": 1},
            "relative": {"type": "boolean", "description": "是否将 x,y 视为相对于当前鼠标位置的偏移", "default": False},
        },
        "required": ["x", "y"]
    }
    
    async def execute(
        self, x: int, y: int, button: str = "left", clicks: int = 1, relative: bool = False,
    ) -> ToolResult:
        if not HAS_PYAUTOGUI:
            return ToolResult(error="pyautogui 未安装")
        try:
            if relative:
                cur = pyautogui.position()
                x, y = cur[0] + x, cur[1] + y
            pyautogui.click(x, y, clicks=clicks, button=button)
            return ToolResult(output=f"已在 ({x}, {y}) 点击 {button} 键 {clicks} 次")
        except OSError as e:
            return ToolResult(error=f"桌面操作错误: {e}")

class MouseMoveTool(BaseTool):
    name = "mouse_move"
    description = "将鼠标移动到指定坐标。"
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"}
        },
        "required": ["x", "y"]
    }
    
    async def execute(self, x: int, y: int) -> ToolResult:
        if not HAS_PYAUTOGUI:
            return ToolResult(error="pyautogui 未安装")
        try:
            pyautogui.moveTo(x, y, duration=0.5)
            return ToolResult(output=f"鼠标已移动到 ({x}, {y})")
        except OSError as e:
            return ToolResult(error=f"桌面操作错误: {e}")

class TypeTextTool(BaseTool):
    name = "type_text"
    description = "在当前光标位置输入文字。注意：需确保目标输入框已聚焦。"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要输入的文字"},
            "interval": {"type": "number", "description": "每个字符间隔（秒）", "default": 0.01}
        },
        "required": ["text"]
    }
    
    async def execute(self, text: str, interval: float = 0.01) -> ToolResult:
        if not HAS_PYAUTOGUI:
            return ToolResult(error="pyautogui 未安装")
        try:
            pyautogui.typewrite(text, interval=interval)
            return ToolResult(output=f"已输入: {text[:50]}{'...' if len(text) > 50 else ''}")
        except OSError as e:
            return ToolResult(error=f"桌面操作错误: {e}")

class PressKeyTool(BaseTool):
    name = "press_key"
    description = "按下键盘按键。支持组合键（如 ctrl+c）。常见按键: enter, tab, esc, space, backspace, delete, ctrl, alt, shift, win, up, down, left, right, f1-f12。"
    parameters = {
        "type": "object",
        "properties": {
            "keys": {
                "type": "array",
                "description": "按键列表，例如 ['ctrl', 'c'] 或 ['enter']",
                "items": {"type": "string"}
            }
        },
        "required": ["keys"]
    }
    
    async def execute(self, keys: list) -> ToolResult:
        if not HAS_PYAUTOGUI:
            return ToolResult(error="pyautogui 未安装")
        try:
            # pyautogui.hotkey 接受多个参数
            pyautogui.hotkey(*keys)
            return ToolResult(output=f"已按下: {'+'.join(keys)}")
        except OSError as e:
            return ToolResult(error=f"桌面操作错误: {e}")

class ScrollTool(BaseTool):
    name = "scroll"
    description = "在鼠标当前位置滚动滚轮。正值向上滚动，负值向下滚动。"
    parameters = {
        "type": "object",
        "properties": {
            "amount": {"type": "integer", "description": "滚动量（正数向上，负数向下）"}
        },
        "required": ["amount"]
    }
    
    async def execute(self, amount: int) -> ToolResult:
        if not HAS_PYAUTOGUI:
            return ToolResult(error="pyautogui 未安装")
        try:
            pyautogui.scroll(amount)
            return ToolResult(output=f"已滚动: {amount}")
        except OSError as e:
            return ToolResult(error=f"桌面操作错误: {e}")

class GetScreenSizeTool(BaseTool):
    name = "get_screen_size"
    description = "获取当前主屏幕的分辨率。"
    parameters = {"type": "object", "properties": {}, "required": []}
    
    async def execute(self) -> ToolResult:
        if not HAS_PYAUTOGUI:
            return ToolResult(error="pyautogui 未安装")
        try:
            w, h = pyautogui.size()
            return ToolResult(output=f"屏幕分辨率: {w}x{h}")
        except OSError as e:
            return ToolResult(error=f"桌面操作错误: {e}")