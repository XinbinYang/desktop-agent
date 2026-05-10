import base64
from typing import Optional
import contextvars
from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, async_playwright
from app.tools.base import BaseTool, ToolResult

# 按 session 隔离的 playwright 实例管理
_BROWSER_SESSION_CTX = contextvars.ContextVar('browser_session', default='default')
_SESSIONS: dict[str, dict] = {}

async def _ensure_browser():
    session_id = _BROWSER_SESSION_CTX.get()
    sess = _SESSIONS.get(session_id)
    
    if sess is None:
        sess = {"playwright": None, "browser": None, "page": None}
        _SESSIONS[session_id] = sess
    
    if sess["playwright"] is None:
        sess["playwright"] = await async_playwright().start()
    if sess["browser"] is None or sess["browser"].is_closed():
        sess["browser"] = await sess["playwright"].chromium.launch(headless=False)
    if sess["page"] is None or sess["page"].is_closed():
        context = await sess["browser"].new_context(viewport={"width": 1280, "height": 800})
        sess["page"] = await context.new_page()
    return sess["page"]

def set_browser_session(session_id: str):
    """设置当前浏览器会话 ID（由 AgentSession 调用）"""
    _BROWSER_SESSION_CTX.set(session_id)

class BrowserNavigateTool(BaseTool):
    name = "browser_navigate"
    description = "在浏览器中打开指定网址。如果没有打开浏览器会自动启动。"
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要访问的 URL"}
        },
        "required": ["url"]
    }
    
    async def execute(self, url: str) -> ToolResult:
        try:
            page = await _ensure_browser()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            title = await page.title()
            return ToolResult(output=f"已打开: {title} ({url})")
        except PlaywrightTimeoutError:
            return ToolResult(error="浏览器操作超时")
        except PlaywrightError as e:
            return ToolResult(error=f"浏览器连接错误: {e}")

class BrowserClickTool(BaseTool):
    name = "browser_click"
    description = "点击页面上的元素。支持 CSS 选择器或文字内容匹配。"
    parameters = {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "CSS 选择器，例如 '#submit' 或 '.btn-primary'"},
            "text": {"type": "string", "description": "如果不提供 selector，则点击包含此文字的元素", "default": ""}
        },
        "required": ["selector"]
    }
    
    async def execute(self, selector: str, text: str = "") -> ToolResult:
        try:
            page = await _ensure_browser()
            if text and not selector:
                await page.get_by_text(text).first.click()
            else:
                await page.click(selector, timeout=10000)
            return ToolResult(output=f"已点击: {selector or text}")
        except PlaywrightTimeoutError:
            return ToolResult(error="浏览器操作超时")
        except PlaywrightError as e:
            return ToolResult(error=f"浏览器连接错误: {e}")

class BrowserTypeTool(BaseTool):
    name = "browser_type"
    description = "在输入框中输入文字。"
    parameters = {
        "type": "object",
        "properties": {
            "selector": {"type": "string", "description": "输入框的 CSS 选择器"},
            "text": {"type": "string", "description": "要输入的文字"},
            "submit": {"type": "boolean", "description": "输入后是否按回车", "default": False}
        },
        "required": ["selector", "text"]
    }
    
    async def execute(self, selector: str, text: str, submit: bool = False) -> ToolResult:
        try:
            page = await _ensure_browser()
            await page.fill(selector, text, timeout=10000)
            if submit:
                await page.press(selector, "Enter")
            return ToolResult(output=f"已在 {selector} 输入文字")
        except PlaywrightTimeoutError:
            return ToolResult(error="浏览器操作超时")
        except PlaywrightError as e:
            return ToolResult(error=f"浏览器连接错误: {e}")

class BrowserScreenshotTool(BaseTool):
    name = "browser_screenshot"
    description = "截取当前浏览器页面的截图，返回 base64 编码。"
    parameters = {
        "type": "object",
        "properties": {},
        "required": []
    }
    
    async def execute(self) -> ToolResult:
        try:
            page = await _ensure_browser()
            screenshot = await page.screenshot(type="png")
            b64 = base64.b64encode(screenshot).decode("utf-8")
            return ToolResult(output="浏览器截图已捕获", base64_image=b64)
        except PlaywrightTimeoutError:
            return ToolResult(error="浏览器操作超时")
        except PlaywrightError as e:
            return ToolResult(error=f"浏览器连接错误: {e}")

class BrowserEvaluateTool(BaseTool):
    name = "browser_evaluate"
    description = "在页面中执行 JavaScript 代码并返回结果。"
    parameters = {
        "type": "object",
        "properties": {
            "script": {"type": "string", "description": "JavaScript 代码"}
        },
        "required": ["script"]
    }
    
    async def execute(self, script: str) -> ToolResult:
        try:
            page = await _ensure_browser()
            result = await page.evaluate(script)
            return ToolResult(output=str(result))
        except PlaywrightTimeoutError:
            return ToolResult(error="浏览器操作超时")
        except PlaywrightError as e:
            return ToolResult(error=f"浏览器连接错误: {e}")

class BrowserCloseTool(BaseTool):
    name = "browser_close"
    description = "关闭浏览器。"
    parameters = {"type": "object", "properties": {}, "required": []}
    
    async def execute(self) -> ToolResult:
        session_id = _BROWSER_SESSION_CTX.get()
        sess = _SESSIONS.pop(session_id, None)
        try:
            if sess:
                if sess.get("page"):
                    await sess["page"].close()
                if sess.get("browser"):
                    await sess["browser"].close()
                if sess.get("playwright"):
                    await sess["playwright"].stop()
            return ToolResult(output="浏览器已关闭")
        except PlaywrightTimeoutError:
            return ToolResult(error="浏览器操作超时")
        except PlaywrightError as e:
            return ToolResult(error=f"浏览器连接错误: {e}")
