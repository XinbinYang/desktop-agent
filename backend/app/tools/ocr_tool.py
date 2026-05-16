"""OCR-powered desktop interaction tools — text-based element targeting."""
from __future__ import annotations

import base64
import io
from typing import Any, Dict, List, Optional

from app.ocr import get_ocr_engine
from app.tools.base import BaseTool, ToolResult
from app.tools.desktop_tool import ScreenshotTool


class OCRClickTool(BaseTool):
    name = "ocr_click"
    description = (
        "Use OCR to find text on screen and click its center. "
        "Much more reliable than coordinate-based mouse_click when targeting labeled UI elements. "
        "Example: ocr_click with text='保存' clicks the Save button."
    )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to find and click on screen (e.g. '保存', 'Submit', 'OK')",
                },
                "language": {
                    "type": "string",
                    "description": "OCR language hint: 'chi_sim+eng' for Chinese+English, 'eng' for English only. Default auto-detects.",
                },
            },
            "required": ["text"],
        }

    async def execute(self, text: str, language: str = "") -> ToolResult:
        import pyautogui

        # Screenshot
        ss_tool = ScreenshotTool()
        ss_result = await ss_tool.execute()
        if not ss_result.base64_image:
            return ToolResult(error="Failed to take screenshot")

        image_bytes = base64.b64decode(ss_result.base64_image)
        engine = get_ocr_engine()

        lang = language or "chi_sim+eng"
        matches = engine.find_text(text, image_bytes, language=lang)

        if not matches:
            available = engine.available_engines()
            return ToolResult(
                output=f"OCR could not find '{text}' on screen. "
                       f"Engines tried: {', '.join(available)}. "
                       f"Try a different text or use mouse_click with approximate coordinates."
            )

        best = matches[0]
        cx, cy = best.center

        pyautogui.click(cx, cy)
        return ToolResult(
            output=(
                f"Clicked '{text}' at ({cx}, {cy}) — "
                f"matched OCR text '{best.text}' (confidence: {best.confidence:.0%}). "
                f"{len(matches)} matches found total."
            ),
            metadata={
                "click_x": cx, "click_y": cy,
                "matched_text": best.text,
                "confidence": best.confidence,
                "total_matches": len(matches),
                "match_details": [m.to_dict() for m in matches[:5]],
            },
        )


class OCRFindTool(BaseTool):
    name = "ocr_find"
    description = (
        "Use OCR to locate text on screen without clicking. "
        "Returns coordinates and confidence scores. "
        "Use this to verify an element exists before interacting with it."
    )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to find on screen",
                },
                "language": {
                    "type": "string",
                    "description": "OCR language hint",
                },
            },
            "required": ["text"],
        }

    async def execute(self, text: str, language: str = "") -> ToolResult:
        ss_tool = ScreenshotTool()
        ss_result = await ss_tool.execute()
        if not ss_result.base64_image:
            return ToolResult(error="Failed to take screenshot")

        image_bytes = base64.b64decode(ss_result.base64_image)
        engine = get_ocr_engine()
        lang = language or "chi_sim+eng"
        matches = engine.find_text(text, image_bytes, language=lang)

        if not matches:
            return ToolResult(output=f"No matches found for '{text}'")

        lines = [f"Found {len(matches)} match(es) for '{text}':"]
        for i, m in enumerate(matches[:10]):
            lines.append(
                f"  [{i+1}] '{m.text}' @ ({m.center[0]}, {m.center[1]}) "
                f"bbox=({m.x},{m.y},{m.width}x{m.height}) conf={m.confidence:.0%}"
            )
        return ToolResult(
            output="\n".join(lines),
            metadata={"matches": [m.to_dict() for m in matches]},
        )


class OCRReadTool(BaseTool):
    name = "ocr_read"
    description = (
        "Use OCR to read all text from the current screen (or a specific region). "
        "Returns structured text with positions. "
        "Use this to understand window content before deciding how to interact."
    )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "x": {
                    "type": "integer",
                    "description": "Region left edge (default: 0 for full screen)",
                },
                "y": {
                    "type": "integer",
                    "description": "Region top edge (default: 0)",
                },
                "width": {
                    "type": "integer",
                    "description": "Region width (default: full screen)",
                },
                "height": {
                    "type": "integer",
                    "description": "Region height (default: full screen)",
                },
                "language": {
                    "type": "string",
                    "description": "OCR language hint",
                },
            },
            "required": [],
        }

    async def execute(
        self,
        x: int = 0, y: int = 0,
        width: int = 0, height: int = 0,
        language: str = "",
    ) -> ToolResult:
        import pyautogui

        ss_tool = ScreenshotTool()
        if width > 0 and height > 0:
            ss_result = await ss_tool.execute(x=x, y=y, width=width, height=height)
        else:
            ss_result = await ss_tool.execute()

        if not ss_result.base64_image:
            return ToolResult(error="Failed to take screenshot")

        image_bytes = base64.b64decode(ss_result.base64_image)
        engine = get_ocr_engine()
        lang = language or "chi_sim+eng"

        results = engine.recognize(image_bytes, language=lang)

        if not results:
            available = engine.available_engines()
            return ToolResult(
                output=f"No text recognized on screen. Engines available: {', '.join(available)}. "
                       f"Install Tesseract for local OCR: https://github.com/UB-Mannheim/tesseract/wiki"
            )

        # Group into lines by y-coordinate proximity
        lines: List[List[OCRResult]] = []
        sorted_results = sorted(results, key=lambda r: (r.y, r.x))
        current_line: List[OCRResult] = []
        current_y = -1

        for r in sorted_results:
            if current_y < 0 or abs(r.y - current_y) < r.height // 2:
                current_line.append(r)
            else:
                if current_line:
                    lines.append(current_line)
                current_line = [r]
            current_y = r.y
        if current_line:
            lines.append(current_line)

        output_lines = [f"Screen text ({len(results)} words, {len(lines)} lines):"]
        for line_words in lines[:30]:
            line_text = " ".join(w.text for w in line_words)
            output_lines.append(f"  {line_text}")

        if len(results) > len([w for line in lines[:30] for w in line]):
            output_lines.append(f"  ... ({len(results) - sum(len(l) for l in lines[:30])} more words)")

        return ToolResult(
            output="\n".join(output_lines),
            metadata={
                "word_count": len(results),
                "line_count": len(lines),
                "words": [r.to_dict() for r in results[:50]],
            },
        )


# Need import for type hint in OCRReadTool
from app.ocr import OCRResult
