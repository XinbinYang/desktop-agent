"""Unified browser/desktop automation tools for observe-act-replay loops."""
from __future__ import annotations

import base64
import time
from typing import Any, Dict, List, Optional, Tuple

from app.automation_runtime import (
    encode_image_bytes,
    encode_pil_image,
    find_element,
    latest_snapshot,
    load_trace,
    new_id,
    now_ms,
    save_snapshot,
    save_trace,
    snapshot_for_trace,
    summarize_elements,
)
from app.tools.base import BaseTool, ToolResult
from app.tools.browser_tool import get_browser_page, has_browser_page, set_browser_session


ACTIONABLE_SELECTOR = (
    "a,button,input,textarea,select,[role],[aria-label],[data-testid],"
    "[contenteditable='true'],summary,[tabindex]"
)


def _coerce_source(source: str, session_id: str) -> str:
    requested = (source or "auto").lower()
    if requested in ("browser", "desktop"):
        return requested
    return "browser" if has_browser_page(session_id) else "desktop"


def _scale_bbox(bbox: Dict[str, Any], sx: float, sy: float) -> Dict[str, int]:
    return {
        "x": round(float(bbox.get("x") or 0) * sx),
        "y": round(float(bbox.get("y") or 0) * sy),
        "width": round(float(bbox.get("width") or 0) * sx),
        "height": round(float(bbox.get("height") or 0) * sy),
    }


def _center_of_bbox(bbox: Dict[str, Any]) -> Tuple[int, int]:
    return (
        int(float(bbox.get("x") or 0) + float(bbox.get("width") or 0) / 2),
        int(float(bbox.get("y") or 0) + float(bbox.get("height") or 0) / 2),
    )


def _element_label(element: Optional[Dict[str, Any]]) -> str:
    if not element:
        return ""
    return str(element.get("name") or element.get("text") or element.get("selector") or element.get("id") or "")


def _target_text(target: Any = None, text: str = "", selector: str = "", element_id: str = "") -> str:
    if isinstance(target, dict):
        for key in ("text", "name", "label", "selector", "element_id", "id"):
            value = target.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(target, str) and target.strip():
        return target.strip()
    return (text or selector or element_id or "").strip()


async def _browser_snapshot(session_id: str, include_screenshot: bool, max_elements: int) -> Dict[str, Any]:
    if session_id:
        set_browser_session(session_id)
    page = await get_browser_page(launch=True)
    data = await page.evaluate(
        """
        (selector) => {
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none' &&
              rect.width >= 2 && rect.height >= 2 &&
              rect.bottom >= 0 && rect.right >= 0 &&
              rect.top <= window.innerHeight && rect.left <= window.innerWidth;
          };
          const cssPath = (el) => {
            if (el.id) return `#${CSS.escape(el.id)}`;
            const testid = el.getAttribute('data-testid');
            if (testid) return `[data-testid="${testid.replace(/"/g, '\\"')}"]`;
            const parts = [];
            let cur = el;
            while (cur && cur.nodeType === Node.ELEMENT_NODE && parts.length < 4) {
              let part = cur.localName;
              if (!part) break;
              const parent = cur.parentElement;
              if (parent) {
                const siblings = Array.from(parent.children).filter((n) => n.localName === cur.localName);
                if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(cur) + 1})`;
              }
              parts.unshift(part);
              cur = parent;
            }
            return parts.join(' > ');
          };
          const inferRole = (el) => {
            const explicit = el.getAttribute('role');
            if (explicit) return explicit;
            const tag = el.localName;
            if (tag === 'a') return 'link';
            if (tag === 'button') return 'button';
            if (tag === 'input') return el.getAttribute('type') || 'textbox';
            if (tag === 'textarea') return 'textbox';
            if (tag === 'select') return 'combobox';
            return tag;
          };
          const nameFor = (el) => {
            const labelledBy = el.getAttribute('aria-labelledby');
            if (labelledBy) {
              const label = document.getElementById(labelledBy);
              if (label?.innerText) return label.innerText.trim();
            }
            return (
              el.getAttribute('aria-label') ||
              el.getAttribute('placeholder') ||
              el.getAttribute('title') ||
              el.getAttribute('alt') ||
              el.value ||
              el.innerText ||
              el.textContent ||
              ''
            ).toString().trim().replace(/\\s+/g, ' ').slice(0, 160);
          };
          const nodes = Array.from(document.querySelectorAll(selector)).filter(visible);
          return {
            title: document.title || '',
            url: location.href,
            viewport: { width: window.innerWidth, height: window.innerHeight },
            elements: nodes.slice(0, 300).map((el, index) => {
              const rect = el.getBoundingClientRect();
              const selectorValue = cssPath(el);
              const role = inferRole(el);
              const name = nameFor(el);
              return {
                id: `browser:dom:${index + 1}`,
                source: 'browser',
                role,
                name,
                text: (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 240),
                selector: selectorValue,
                bbox: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                attributes: {
                  tag: el.localName,
                  type: el.getAttribute('type') || '',
                  aria_label: el.getAttribute('aria-label') || '',
                  testid: el.getAttribute('data-testid') || '',
                  href: el.getAttribute('href') || '',
                  disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true'),
                },
              };
            }),
          };
        }
        """,
        ACTIONABLE_SELECTOR,
    )

    screenshot: Dict[str, Any] = {}
    shot_width = int(data.get("viewport", {}).get("width") or 1280)
    shot_height = int(data.get("viewport", {}).get("height") or 800)
    if include_screenshot:
        image_bytes = await page.screenshot(type="png")
        b64, shot_width, shot_height = encode_image_bytes(image_bytes)
        screenshot = {"base64": b64, "width": shot_width, "height": shot_height}

    viewport = data.get("viewport") or {"width": shot_width, "height": shot_height}
    sx = shot_width / max(float(viewport.get("width") or shot_width), 1)
    sy = shot_height / max(float(viewport.get("height") or shot_height), 1)
    elements: List[Dict[str, Any]] = []
    for raw in (data.get("elements") or [])[:max_elements]:
        element = dict(raw)
        element["attributes"] = dict(element.get("attributes") or {})
        element["attributes"]["browser_bbox"] = dict(element.get("bbox") or {})
        element["bbox"] = _scale_bbox(element.get("bbox") or {}, sx, sy)
        elements.append(element)

    snapshot = {
        "snapshot_id": new_id("snap"),
        "session_id": session_id or "default",
        "source": "browser",
        "timestamp": now_ms(),
        "title": data.get("title") or "Browser",
        "url": data.get("url") or "",
        "viewport": {"width": shot_width, "height": shot_height},
        "screenshot": screenshot,
        "elements": elements,
        "element_count": len(elements),
    }
    return save_snapshot(session_id, snapshot)


async def _desktop_snapshot(session_id: str, include_screenshot: bool, max_elements: int) -> Dict[str, Any]:
    import pyautogui

    screen_w, screen_h = pyautogui.size()
    screenshot: Dict[str, Any] = {}
    sx = sy = 1.0
    if include_screenshot:
        img = pyautogui.screenshot()
        b64, shot_w, shot_h = encode_pil_image(img)
        sx = shot_w / max(float(screen_w), 1)
        sy = shot_h / max(float(screen_h), 1)
        screenshot = {"base64": b64, "width": shot_w, "height": shot_h}
    else:
        shot_w, shot_h = int(screen_w), int(screen_h)

    elements: List[Dict[str, Any]] = []

    try:
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        windows = desktop.windows()
        for window_index, win in enumerate(windows[:30]):
            try:
                title = win.window_text()
                rect = win.rectangle()
                if not title or rect.width() <= 0 or rect.height() <= 0:
                    continue
                bbox = {
                    "x": rect.left,
                    "y": rect.top,
                    "width": rect.width(),
                    "height": rect.height(),
                }
                elements.append({
                    "id": f"desktop:uia:{len(elements) + 1}",
                    "source": "desktop",
                    "role": "window",
                    "name": title,
                    "text": title,
                    "bbox": _scale_bbox(bbox, sx, sy),
                    "attributes": {
                        "backend": "uia",
                        "window_index": window_index,
                        "actual_bbox": bbox,
                    },
                })
                try:
                    for child in win.descendants()[:80]:
                        if len(elements) >= max_elements:
                            break
                        ctext = child.window_text()
                        crect = child.rectangle()
                        if crect.width() <= 0 or crect.height() <= 0:
                            continue
                        control_type = ""
                        try:
                            control_type = child.element_info.control_type or ""
                        except Exception:
                            pass
                        if not ctext and control_type not in ("Button", "Edit", "ComboBox", "MenuItem", "TabItem"):
                            continue
                        cbbox = {
                            "x": crect.left,
                            "y": crect.top,
                            "width": crect.width(),
                            "height": crect.height(),
                        }
                        elements.append({
                            "id": f"desktop:uia:{len(elements) + 1}",
                            "source": "desktop",
                            "role": control_type or "control",
                            "name": ctext or control_type,
                            "text": ctext,
                            "bbox": _scale_bbox(cbbox, sx, sy),
                            "attributes": {
                                "backend": "uia",
                                "window_title": title,
                                "control_type": control_type,
                                "actual_bbox": cbbox,
                            },
                        })
                except Exception:
                    continue
                if len(elements) >= max_elements:
                    break
            except Exception:
                continue
    except Exception:
        pass

    if include_screenshot and len(elements) < max_elements:
        try:
            from app.ocr import get_ocr_engine

            image_bytes = base64.b64decode(screenshot.get("base64") or "")
            for idx, word in enumerate(get_ocr_engine().recognize(image_bytes)[: max_elements - len(elements)]):
                actual_bbox = {
                    "x": int(word.x / max(sx, 0.001)),
                    "y": int(word.y / max(sy, 0.001)),
                    "width": int(word.width / max(sx, 0.001)),
                    "height": int(word.height / max(sy, 0.001)),
                }
                elements.append({
                    "id": f"desktop:ocr:{idx + 1}",
                    "source": "desktop",
                    "role": "text",
                    "name": word.text,
                    "text": word.text,
                    "bbox": {
                        "x": int(word.x),
                        "y": int(word.y),
                        "width": int(word.width),
                        "height": int(word.height),
                    },
                    "confidence": word.confidence,
                    "attributes": {"backend": "ocr", "actual_bbox": actual_bbox},
                })
        except Exception:
            pass

    snapshot = {
        "snapshot_id": new_id("snap"),
        "session_id": session_id or "default",
        "source": "desktop",
        "timestamp": now_ms(),
        "title": "Desktop",
        "viewport": {"width": shot_w, "height": shot_h},
        "screenshot": screenshot,
        "elements": elements[:max_elements],
        "element_count": min(len(elements), max_elements),
    }
    return save_snapshot(session_id, snapshot)


async def observe_automation(
    session_id: str,
    source: str = "auto",
    include_screenshot: bool = True,
    max_elements: int = 120,
) -> Dict[str, Any]:
    resolved = _coerce_source(source, session_id)
    if resolved == "browser":
        return await _browser_snapshot(session_id, include_screenshot, max_elements)
    return await _desktop_snapshot(session_id, include_screenshot, max_elements)


async def _resolve_browser_locator(
    target: Any = None,
    selector: str = "",
    text: str = "",
    element_id: str = "",
    session_id: str = "",
):
    if session_id:
        set_browser_session(session_id)
    page = await get_browser_page(launch=True)
    snapshot = latest_snapshot(session_id)
    element = find_element(snapshot, element_id)
    if not element and isinstance(target, dict):
        element = find_element(snapshot, str(target.get("element_id") or target.get("id") or ""))
    if element:
        sel = element.get("selector")
        if sel:
            return page.locator(sel).first, element, [f"element_id:{element.get('id')}", f"selector:{sel}"]

    if isinstance(target, dict):
        selector = selector or str(target.get("selector") or "")
        text = text or str(target.get("text") or target.get("name") or target.get("label") or "")
    elif isinstance(target, str) and target.strip() and not text and not selector:
        text = target.strip()

    if selector:
        return page.locator(selector).first, None, [f"selector:{selector}"]
    if text:
        return page.get_by_text(text, exact=False).first, None, [f"text:{text}"]
    raise ValueError("browser target requires selector, text, or element_id")


async def _click_browser(
    session_id: str,
    target: Any = None,
    selector: str = "",
    text: str = "",
    element_id: str = "",
    button: str = "left",
    clicks: int = 1,
) -> tuple[Optional[dict[str, Any]], List[str]]:
    locator, element, chain = await _resolve_browser_locator(target, selector, text, element_id, session_id)
    await locator.click(button=button, click_count=max(1, int(clicks or 1)), timeout=10000)
    return element, chain


async def _type_browser(
    session_id: str,
    value: str,
    target: Any = None,
    selector: str = "",
    text: str = "",
    element_id: str = "",
    submit: bool = False,
    clear: bool = True,
) -> tuple[Optional[dict[str, Any]], List[str]]:
    locator, element, chain = await _resolve_browser_locator(target, selector, text, element_id, session_id)
    if clear:
        await locator.fill(value, timeout=10000)
    else:
        await locator.type(value, timeout=10000)
    if submit:
        await locator.press("Enter")
    return element, chain


async def _desktop_point_for_target(
    session_id: str,
    target: Any = None,
    text: str = "",
    element_id: str = "",
    x: int = 0,
    y: int = 0,
) -> tuple[Tuple[int, int], Optional[dict[str, Any]], List[str]]:
    snapshot = latest_snapshot(session_id)
    element = find_element(snapshot, element_id)
    if not element and isinstance(target, dict):
        element = find_element(snapshot, str(target.get("element_id") or target.get("id") or ""))
    if element:
        actual = (element.get("attributes") or {}).get("actual_bbox") or element.get("bbox") or {}
        point = _center_of_bbox(actual)
        return point, element, [f"element_id:{element.get('id')}"]

    if isinstance(target, dict):
        text = text or str(target.get("text") or target.get("name") or target.get("label") or "")
        x = int(target.get("x") or x or 0)
        y = int(target.get("y") or y or 0)
    elif isinstance(target, str) and target.strip() and not text:
        text = target.strip()

    if text:
        from app.ocr import get_smart_locator

        located = await get_smart_locator().locate(text)
        if located:
            return located, None, [f"ocr_or_uia_text:{text}"]
    if x or y:
        return (int(x), int(y)), None, [f"coordinates:{x},{y}"]
    raise ValueError("desktop target requires text, element_id, or coordinates")


async def _click_desktop(
    session_id: str,
    target: Any = None,
    text: str = "",
    element_id: str = "",
    x: int = 0,
    y: int = 0,
    button: str = "left",
    clicks: int = 1,
) -> tuple[Optional[dict[str, Any]], List[str]]:
    import pyautogui

    point, element, chain = await _desktop_point_for_target(session_id, target, text, element_id, x, y)
    pyautogui.click(point[0], point[1], clicks=max(1, int(clicks or 1)), button=button)
    return element, chain


async def _type_desktop(
    session_id: str,
    value: str,
    target: Any = None,
    text: str = "",
    element_id: str = "",
    submit: bool = False,
    clear: bool = False,
) -> tuple[Optional[dict[str, Any]], List[str]]:
    import pyautogui

    element: Optional[Dict[str, Any]] = None
    chain: List[str] = []
    target_label = _target_text(target, text=text, element_id=element_id)
    if target_label:
        element, chain = await _click_desktop(session_id, target, text=text, element_id=element_id)
    if clear:
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
    pyautogui.typewrite(value, interval=0.01)
    if submit:
        pyautogui.press("enter")
    return element, chain or ["focused_element"]


async def _record_action(
    session_id: str,
    action_type: str,
    source: str,
    args: Dict[str, Any],
    perform,
) -> ToolResult:
    started = time.time()
    before = await observe_automation(session_id, source=source, include_screenshot=True)
    action: Dict[str, Any] = {
        "action_id": new_id("act"),
        "type": action_type,
        "source": before.get("source") or source,
        "args": args,
        "status": "running",
        "started_at": now_ms(),
        "before_snapshot_id": before.get("snapshot_id"),
        "before_snapshot": snapshot_for_trace(before),
    }
    try:
        element, chain = await perform(before.get("source") or source)
        action["status"] = "success"
        action["resolved_element"] = element
        action["locator_chain"] = chain
    except Exception as exc:
        action["status"] = "error"
        action["error"] = str(exc)
    after = await observe_automation(session_id, source=before.get("source") or source, include_screenshot=True)
    action["after_snapshot_id"] = after.get("snapshot_id")
    action["after_snapshot"] = snapshot_for_trace(after)
    action["duration_ms"] = round((time.time() - started) * 1000)
    trace = save_trace(session_id, {
        "trace_id": new_id("trace"),
        "session_id": session_id or "default",
        "source": before.get("source") or source,
        "actions": [action],
        "created_at": action["started_at"],
    })
    label = _element_label(action.get("resolved_element")) or _target_text(args.get("target"), args.get("text", ""), args.get("selector", ""), args.get("element_id", ""))
    output = f"{action_type} {action['status']}"
    if label:
        output += f": {label}"
    if action.get("error"):
        output += f"\n{action['error']}"
    return ToolResult(
        output=output,
        error=action.get("error", ""),
        metadata={
            "automation_snapshot": after,
            "automation_action": action,
            "automation_trace": trace,
        },
    )


class AutomationObserveTool(BaseTool):
    name = "automation_observe"
    description = (
        "Observe the current browser page or Windows desktop. Returns a screenshot, "
        "semantic element tree, and stable element ids for robust follow-up actions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "enum": ["auto", "browser", "desktop"], "default": "auto"},
            "include_screenshot": {"type": "boolean", "default": True},
            "max_elements": {"type": "integer", "default": 120},
        },
        "required": [],
    }

    async def execute(
        self,
        source: str = "auto",
        include_screenshot: bool = True,
        max_elements: int = 120,
        session_id: str = "",
    ) -> ToolResult:
        snapshot = await observe_automation(
            session_id=session_id or "default",
            source=source,
            include_screenshot=include_screenshot,
            max_elements=max(20, min(int(max_elements or 120), 300)),
        )
        lines = [
            f"Automation snapshot {snapshot['snapshot_id']} ({snapshot['source']})",
            f"Title: {snapshot.get('title') or snapshot.get('url') or 'Desktop'}",
            f"Elements: {snapshot.get('element_count', 0)}",
        ]
        summary = summarize_elements(snapshot.get("elements") or [])
        if summary:
            lines.append(summary)
        return ToolResult(output="\n".join(lines), metadata={"automation_snapshot": snapshot})


class AutomationClickTool(BaseTool):
    name = "automation_click"
    description = "Click a browser or desktop element using semantic selectors, text, element_id, OCR, or coordinates as fallback."
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "enum": ["auto", "browser", "desktop"], "default": "auto"},
            "target": {
                "anyOf": [{"type": "object"}, {"type": "string"}],
                "description": "Semantic target: {element_id, selector, text, name, x, y} or a text label.",
            },
            "element_id": {"type": "string", "default": ""},
            "selector": {"type": "string", "default": ""},
            "text": {"type": "string", "default": ""},
            "x": {"type": "integer", "default": 0},
            "y": {"type": "integer", "default": 0},
            "button": {"type": "string", "default": "left"},
            "clicks": {"type": "integer", "default": 1},
        },
        "required": [],
    }

    async def execute(
        self,
        source: str = "auto",
        target: Any = None,
        element_id: str = "",
        selector: str = "",
        text: str = "",
        x: int = 0,
        y: int = 0,
        button: str = "left",
        clicks: int = 1,
        session_id: str = "",
    ) -> ToolResult:
        sid = session_id or "default"
        args = {
            "target": target,
            "element_id": element_id,
            "selector": selector,
            "text": text,
            "x": x,
            "y": y,
            "button": button,
            "clicks": clicks,
        }

        async def perform(resolved_source: str):
            if resolved_source == "browser":
                return await _click_browser(sid, target, selector, text, element_id, button, clicks)
            return await _click_desktop(sid, target, text, element_id, x, y, button, clicks)

        return await _record_action(sid, "click", _coerce_source(source, sid), args, perform)


class AutomationTypeTool(BaseTool):
    name = "automation_type"
    description = "Type into a browser or desktop target using semantic locator first and coordinates only as fallback."
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to type"},
            "source": {"type": "string", "enum": ["auto", "browser", "desktop"], "default": "auto"},
            "target": {
                "anyOf": [{"type": "object"}, {"type": "string"}],
                "description": "Input target: {element_id, selector, text, name} or a label.",
            },
            "element_id": {"type": "string", "default": ""},
            "selector": {"type": "string", "default": ""},
            "label": {"type": "string", "default": ""},
            "submit": {"type": "boolean", "default": False},
            "clear": {"type": "boolean", "default": True},
        },
        "required": ["text"],
    }

    async def execute(
        self,
        text: str,
        source: str = "auto",
        target: Any = None,
        element_id: str = "",
        selector: str = "",
        label: str = "",
        submit: bool = False,
        clear: bool = True,
        session_id: str = "",
    ) -> ToolResult:
        sid = session_id or "default"
        args = {
            "target": target,
            "element_id": element_id,
            "selector": selector,
            "label": label,
            "text": text,
            "text_preview": text[:80],
            "submit": submit,
            "clear": clear,
        }

        async def perform(resolved_source: str):
            if resolved_source == "browser":
                return await _type_browser(sid, text, target, selector, label, element_id, submit, clear)
            return await _type_desktop(sid, text, target, label, element_id, submit, clear)

        return await _record_action(sid, "type", _coerce_source(source, sid), args, perform)


class AutomationKeyTool(BaseTool):
    name = "automation_key"
    description = "Press one key or a key chord in the current browser/desktop focus."
    parameters = {
        "type": "object",
        "properties": {
            "keys": {"type": "array", "items": {"type": "string"}, "description": "Example: ['ctrl','l'] or ['enter']"},
            "source": {"type": "string", "enum": ["auto", "browser", "desktop"], "default": "auto"},
        },
        "required": ["keys"],
    }

    async def execute(self, keys: List[str], source: str = "auto", session_id: str = "") -> ToolResult:
        sid = session_id or "default"
        args = {"keys": keys}

        async def perform(resolved_source: str):
            if resolved_source == "browser":
                if sid:
                    set_browser_session(sid)
                page = await get_browser_page(launch=True)
                if len(keys) == 1:
                    await page.keyboard.press(keys[0])
                else:
                    await page.keyboard.press("+".join(keys))
                return None, [f"browser_key:{'+'.join(keys)}"]
            import pyautogui

            pyautogui.hotkey(*keys)
            return None, [f"desktop_key:{'+'.join(keys)}"]

        return await _record_action(sid, "key", _coerce_source(source, sid), args, perform)


class AutomationScrollTool(BaseTool):
    name = "automation_scroll"
    description = "Scroll the current browser page or desktop at the current pointer/focus."
    parameters = {
        "type": "object",
        "properties": {
            "amount": {"type": "integer", "description": "Positive scrolls up, negative scrolls down"},
            "source": {"type": "string", "enum": ["auto", "browser", "desktop"], "default": "auto"},
        },
        "required": ["amount"],
    }

    async def execute(self, amount: int, source: str = "auto", session_id: str = "") -> ToolResult:
        sid = session_id or "default"
        args = {"amount": amount}

        async def perform(resolved_source: str):
            if resolved_source == "browser":
                if sid:
                    set_browser_session(sid)
                page = await get_browser_page(launch=True)
                await page.mouse.wheel(0, -int(amount) * 120)
                return None, [f"browser_scroll:{amount}"]
            import pyautogui

            pyautogui.scroll(int(amount))
            return None, [f"desktop_scroll:{amount}"]

        return await _record_action(sid, "scroll", _coerce_source(source, sid), args, perform)


class AutomationReplayTool(BaseTool):
    name = "automation_replay"
    description = "Replay a saved semantic automation trace. Used by the Inspector replay controls."
    parameters = {
        "type": "object",
        "properties": {
            "trace_id": {"type": "string"},
            "from_step": {"type": "integer", "default": 0},
            "to_step": {"type": "integer", "default": -1},
        },
        "required": ["trace_id"],
    }

    async def execute(
        self,
        trace_id: str,
        from_step: int = 0,
        to_step: int = -1,
        session_id: str = "",
    ) -> ToolResult:
        sid = session_id or "default"
        trace = load_trace(sid, trace_id)
        if not trace:
            return ToolResult(error=f"Automation trace not found: {trace_id}")
        actions = list(trace.get("actions") or [])
        end = len(actions) if to_step is None or int(to_step) < 0 else min(len(actions), int(to_step) + 1)
        selected = actions[max(0, int(from_step or 0)):end]
        replay_events: List[Dict[str, Any]] = []
        errors: List[str] = []
        for index, action in enumerate(selected, start=max(0, int(from_step or 0))):
            action_type = action.get("type")
            args = dict(action.get("args") or {})
            source = str(action.get("source") or trace.get("source") or "auto")
            try:
                if action_type == "click":
                    result = await AutomationClickTool().execute(source=source, session_id=sid, **args)
                elif action_type == "type":
                    value = args.pop("text", "") or args.pop("value", "")
                    args.pop("text_preview", None)
                    value = value or action.get("text") or ""
                    result = await AutomationTypeTool().execute(text=value, source=source, session_id=sid, **args)
                elif action_type == "key":
                    result = await AutomationKeyTool().execute(keys=args.get("keys") or [], source=source, session_id=sid)
                elif action_type == "scroll":
                    result = await AutomationScrollTool().execute(amount=int(args.get("amount") or 0), source=source, session_id=sid)
                else:
                    continue
                replay_events.append({"step": index, "status": "error" if result.error else "success", "output": result.output})
                if result.error:
                    errors.append(result.error)
                    break
            except Exception as exc:
                errors.append(str(exc))
                replay_events.append({"step": index, "status": "error", "output": str(exc)})
                break
        status = {
            "trace_id": trace_id,
            "status": "error" if errors else "completed",
            "from_step": from_step,
            "to_step": end - 1 if selected else from_step,
            "events": replay_events,
            "error": errors[0] if errors else "",
        }
        return ToolResult(
            output=f"Replay {status['status']}: {len(replay_events)} step(s)",
            error=status["error"],
            metadata={"automation_replay_status": status},
        )
