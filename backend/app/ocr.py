"""OCR engine for screen text recognition and UI element localization.

Three-layer strategy:
  1. Windows OCR API (system-native, zero install, best Chinese accuracy)
  2. Tesseract (open-source, cross-platform, needs install)
  3. LLM Vision (always available as final fallback)
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageEnhance, ImageFilter

logger = logging.getLogger(__name__)

# ── data types ──────────────────────────────────────────────────────────────

@dataclass
class OCRResult:
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 0.0

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "x": self.x, "y": self.y,
            "width": self.width, "height": self.height,
            "confidence": round(self.confidence, 3),
            "center": list(self.center),
        }


# ── image pre-processing ────────────────────────────────────────────────────

def _preprocess_for_ocr(image_bytes: bytes) -> Image.Image:
    """Enhance screenshot for better OCR accuracy."""
    img = Image.open(io.BytesIO(image_bytes)).convert("L")  # grayscale
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(2.0)
    # Mild sharpening
    img = img.filter(ImageFilter.SHARPEN)
    return img


# ── engine detection ────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _detect_available_engines() -> List[str]:
    """Return list of available OCR engines in preference order."""
    available: List[str] = []

    # 1. Windows OCR (check if winrt package is actually importable)
    if os.name == "nt":
        try:
            import winrt.windows.media.ocr  # noqa: F401
            available.append("winrt")
        except ImportError:
            logger.debug("winrt package not installed, Windows OCR unavailable")

    # 2. Tesseract
    if shutil.which("tesseract") or shutil.which("tesseract.exe"):
        available.append("tesseract")

    # 3. LLM Vision (always available)
    available.append("vision")

    return available


def get_available_engines() -> List[str]:
    return _detect_available_engines()


# ── Windows OCR engine ──────────────────────────────────────────────────────

def _ocr_winrt(image_bytes: bytes, language: str = "") -> List[OCRResult]:
    """Use Windows 10+ built-in OCR API."""
    results: List[OCRResult] = []

    try:
        import winrt.windows.media.ocr as win_ocr
        import winrt.windows.graphics.imaging as win_img
        import winrt.windows.storage.streams as win_streams
    except ImportError:
        logger.debug("winrt not available, skip Windows OCR")
        return results

    # Save image bytes to temp file (winrt needs a file path or stream)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(image_bytes)
        tmp_path = f.name

    try:
        # Open image via Windows Runtime
        file = win_streams.RandomAccessStreamReference.create_from_file(tmp_path)
        decoder = win_img.BitmapDecoder.create_async(file).get()
        bitmap = win_img.SoftwareBitmap.convert(
            decoder.get_software_bitmap_async().get(),
            win_img.BitmapPixelFormat.bgra8,
        )

        engine = win_ocr.OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            return results

        ocr_result = engine.recognize_async(bitmap).get()
        if ocr_result is None:
            return results

        for line in ocr_result.lines:
            for word in line.words:
                rect = word.bounding_rect
                results.append(OCRResult(
                    text=word.text,
                    x=rect.x, y=rect.y,
                    width=rect.width, height=rect.height,
                    confidence=1.0,  # winrt doesn't expose per-word confidence
                ))
    except Exception as e:
        logger.debug("Windows OCR failed: %s", e)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return results


# ── Tesseract engine ────────────────────────────────────────────────────────

def _ocr_tesseract(image_bytes: bytes, language: str = "chi_sim+eng") -> List[OCRResult]:
    """Use Tesseract OCR with bounding box output (tsv format)."""
    results: List[OCRResult] = []

    tesseract_bin = shutil.which("tesseract") or shutil.which("tesseract.exe")
    if not tesseract_bin:
        return results

    img = _preprocess_for_ocr(image_bytes)

    with tempfile.TemporaryDirectory() as tmpdir:
        img_path = os.path.join(tmpdir, "screenshot.png")
        out_base = os.path.join(tmpdir, "output")
        img.save(img_path, "PNG")

        try:
            subprocess.run(
                [tesseract_bin, img_path, out_base, "-l", language, "--psm", "6", "tsv"],
                capture_output=True, text=True, timeout=15, check=True,
                encoding="utf-8", errors="replace",
            )
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
            logger.debug("Tesseract execution failed")
            return results

        tsv_path = out_base + ".tsv"
        if not os.path.exists(tsv_path):
            return results

        try:
            with open(tsv_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return results

        # Parse TSV: header at line 1, data from line 2
        if len(lines) < 2:
            return results

        headers = lines[0].strip().split("\t")
        try:
            text_idx = headers.index("text")
            conf_idx = headers.index("conf")
            left_idx = headers.index("left")
            top_idx = headers.index("top")
            width_idx = headers.index("width")
            height_idx = headers.index("height")
            level_idx = headers.index("level")
        except ValueError:
            return results

        for line in lines[1:]:
            cols = line.strip().split("\t")
            if len(cols) <= max(text_idx, conf_idx, width_idx, height_idx):
                continue
            try:
                level = int(cols[level_idx])
                if level != 5:  # word level
                    continue
                text = cols[text_idx].strip()
                if not text:
                    continue
                conf = float(cols[conf_idx])
                if conf < 0:
                    continue
                results.append(OCRResult(
                    text=text,
                    x=int(float(cols[left_idx])),
                    y=int(float(cols[top_idx])),
                    width=int(float(cols[width_idx])),
                    height=int(float(cols[height_idx])),
                    confidence=conf / 100.0,
                ))
            except (ValueError, IndexError):
                continue

    return results


# ── LLM Vision fallback ─────────────────────────────────────────────────────

async def _ocr_vision(
    text_to_find: str,
    screenshot_base64: str,
    model_id: str = "",
) -> List[OCRResult]:
    """Use LLM vision to locate text in screenshot. Returns coordinate estimates."""
    # This is a fallback — the existing auto-screenshot flow already does this.
    # We encode a specific prompt asking the model to locate the text.
    # For now, return empty; the caller should use the existing vision flow.
    return []


# ── unified engine ──────────────────────────────────────────────────────────

class OCREngine:
    """High-level OCR engine with automatic engine selection and caching."""

    def __init__(self):
        self._cache: Dict[str, List[OCRResult]] = {}  # hash -> results
        self._max_cache = 8

    @staticmethod
    def available_engines() -> List[str]:
        return get_available_engines()

    @staticmethod
    def is_available() -> bool:
        engines = get_available_engines()
        return any(e in ("winrt", "tesseract") for e in engines)

    @staticmethod
    def has_local_engine() -> bool:
        """Check if a local (non-LLM) OCR engine is available."""
        return OCREngine.is_available()

    def _cache_key(self, image_bytes: bytes) -> str:
        return hashlib.sha256(image_bytes).hexdigest()[:16]

    def _cache_get(self, key: str) -> Optional[List[OCRResult]]:
        return self._cache.get(key)

    def _cache_set(self, key: str, results: List[OCRResult]):
        if len(self._cache) >= self._max_cache:
            # Evict oldest
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[key] = results

    def recognize(
        self,
        image_bytes: bytes,
        language: str = "chi_sim+eng",
        preferred_engine: str = "",
    ) -> List[OCRResult]:
        """Recognize all text in an image using the best available engine.

        Returns list of OCRResult sorted by confidence descending.
        """
        key = self._cache_key(image_bytes)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        results: List[OCRResult] = []
        available = get_available_engines()

        for engine in available:
            if preferred_engine and engine != preferred_engine:
                continue
            if engine == "winrt":
                results = _ocr_winrt(image_bytes, language)
            elif engine == "tesseract":
                results = _ocr_tesseract(image_bytes, language)
            elif engine == "vision":
                continue  # handled separately via async flow
            if results:
                break

        # Sort by confidence descending
        results.sort(key=lambda r: r.confidence, reverse=True)
        self._cache_set(key, results)
        return results

    def find_text(
        self,
        text: str,
        image_bytes: bytes,
        language: str = "chi_sim+eng",
        min_similarity: float = 0.6,
    ) -> List[OCRResult]:
        """Find screen positions of specified text.

        Returns matches sorted by similarity descending.
        """
        all_results = self.recognize(image_bytes, language)

        text_lower = text.lower().strip()
        matches: List[Tuple[float, OCRResult]] = []

        for r in all_results:
            r_text_lower = r.text.lower().strip()

            # Exact match
            if r_text_lower == text_lower:
                matches.append((1.0, r))
                continue

            # Substring match
            if text_lower in r_text_lower or r_text_lower in text_lower:
                sim = min(len(text_lower), len(r_text_lower)) / max(len(text_lower), len(r_text_lower))
                if sim >= min_similarity:
                    matches.append((sim * 0.9, r))
                    continue

            # Fuzzy: simple character overlap
            common = sum(1 for c in text_lower if c in r_text_lower)
            sim = common / max(len(text_lower), 1)
            if sim >= min_similarity:
                matches.append((sim * 0.7, r))

        matches.sort(key=lambda x: x[0], reverse=True)
        return [m[1] for m in matches]

    def read_region(
        self,
        image_bytes: bytes,
        x: int, y: int, width: int, height: int,
        language: str = "chi_sim+eng",
    ) -> List[OCRResult]:
        """Read text within a specific screen region."""
        all_results = self.recognize(image_bytes, language)
        return [
            r for r in all_results
            if r.x >= x and r.y >= y
            and r.x + r.width <= x + width
            and r.y + r.height <= y + height
        ]


# ── SmartLocator: multi-tier fallback ───────────────────────────────────────

class SmartLocator:
    """Multi-tier element locator with fallback chain.

    Strategy (in order):
      1. UIA accessibility tree (Windows native, fastest)
      2. OCR text recognition (cross-platform, local)
      3. LLM Vision (always available, slowest)
    """

    def __init__(self):
        self.ocr = get_ocr_engine()
        self._cache: Dict[str, Optional[Tuple[int, int]]] = {}

    async def locate(self, target: str) -> Optional[Tuple[int, int]]:
        """Find screen coordinates for a UI element by text label.

        Returns (x, y) center coordinates or None.
        """
        # Check cache
        cache_key = target.lower().strip()
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Strategy 1: UIA accessibility tree
        result = self._locate_uia(target)
        if result:
            self._cache[cache_key] = result
            return result

        # Strategy 2: OCR
        result = await self._locate_ocr(target)
        if result:
            self._cache[cache_key] = result
            return result

        # Strategy 3: LLM Vision (caller handles via existing vision flow)
        return None

    def _locate_uia(self, target: str) -> Optional[Tuple[int, int]]:
        """Use Windows UIA to find a control by name."""
        if os.name != "nt":
            return None
        try:
            from app.tools.app_tool import AppFindWindowTool
            # AppFindWindowTool already returns window rect info
            # For fine-grained control lookup, we'd need deeper UIA
            # For now, this is a fast path for window-level targeting
            return None  # Defer to OCR for button-level precision
        except Exception:
            return None

    async def _locate_ocr(self, target: str) -> Optional[Tuple[int, int]]:
        """Use OCR to locate text on screen."""
        import base64
        from app.tools.desktop_tool import ScreenshotTool

        try:
            ss = ScreenshotTool()
            result = await ss.execute()
            if not result.base64_image:
                return None
            image_bytes = base64.b64decode(result.base64_image)
            matches = self.ocr.find_text(target, image_bytes)
            if matches:
                best = matches[0]
                return best.center
        except Exception as e:
            logger.debug("SmartLocator OCR failed: %s", e)
        return None

    def clear_cache(self):
        self._cache.clear()


# ── singleton ───────────────────────────────────────────────────────────────

_engine: Optional[OCREngine] = None
_locator: Optional[SmartLocator] = None


def get_ocr_engine() -> OCREngine:
    global _engine
    if _engine is None:
        _engine = OCREngine()
    return _engine


def get_smart_locator() -> SmartLocator:
    global _locator
    if _locator is None:
        _locator = SmartLocator()
    return _locator
