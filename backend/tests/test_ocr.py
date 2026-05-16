"""Tests for OCR engine — engine detection, image preprocessing, result types."""
import io
from pathlib import Path
from PIL import Image
from app.ocr import (
    OCRResult,
    OCREngine,
    SmartLocator,
    get_available_engines,
    get_ocr_engine,
    get_smart_locator,
    _preprocess_for_ocr,
)


class TestOCRResult:
    def test_center_calculation(self):
        r = OCRResult(text="Save", x=100, y=50, width=80, height=30)
        assert r.center == (140, 65)

    def test_to_dict(self):
        r = OCRResult(text="Save", x=10, y=20, width=30, height=15, confidence=0.95)
        d = r.to_dict()
        assert d["text"] == "Save"
        assert d["confidence"] == 0.95
        assert d["center"] == [25, 27]


class TestImagePreprocessing:
    def test_preprocess_returns_image(self):
        img = Image.new("RGB", (100, 50), "white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = _preprocess_for_ocr(buf.getvalue())
        assert isinstance(result, Image.Image)
        assert result.mode == "L"  # Grayscale

    def test_preprocess_enhances_contrast(self):
        # Dark text on light background
        img = Image.new("RGB", (100, 50), "white")
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), "Test", fill="black")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        result = _preprocess_for_ocr(buf.getvalue())
        assert result.size == img.size


class TestEngineDetection:
    def test_returns_list(self):
        engines = get_available_engines()
        assert isinstance(engines, list)
        assert len(engines) >= 1  # At minimum 'vision'

    def test_vision_always_available(self):
        assert "vision" in get_available_engines()

    def test_is_available(self):
        avail = OCREngine.is_available()
        assert isinstance(avail, bool)

    def test_has_local_engine(self):
        has = OCREngine.has_local_engine()
        assert isinstance(has, bool)


class TestOCREngine:
    def test_singleton(self):
        e1 = get_ocr_engine()
        e2 = get_ocr_engine()
        assert e1 is e2

    def test_recognize_empty_image(self):
        engine = OCREngine()
        img = Image.new("RGB", (100, 50), "white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        results = engine.recognize(buf.getvalue())
        # With no OCR engines installed (beyond vision), results will be empty
        assert isinstance(results, list)

    def test_find_text_no_match(self):
        engine = OCREngine()
        img = Image.new("RGB", (100, 50), "white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        results = engine.find_text("Nonexistent", buf.getvalue())
        assert results == []

    def test_cache_works(self):
        engine = OCREngine()
        img = Image.new("RGB", (100, 50), "white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        r1 = engine.recognize(image_bytes)
        r2 = engine.recognize(image_bytes)
        # Same call should hit cache (both return same list object or same content)
        assert r1 == r2

    def test_read_region(self):
        engine = OCREngine()
        img = Image.new("RGB", (200, 100), "white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        results = engine.read_region(buf.getvalue(), 0, 0, 50, 50)
        assert isinstance(results, list)

    def test_available_engines_static(self):
        engines = OCREngine.available_engines()
        assert isinstance(engines, list)


class TestSmartLocator:
    def test_singleton(self):
        s1 = get_smart_locator()
        s2 = get_smart_locator()
        assert s1 is s2

    def test_clear_cache(self):
        locator = SmartLocator()
        locator._cache["test"] = (100, 200)
        locator.clear_cache()
        assert locator._cache == {}
