"""
Unit tests for OCR data models and factory function.

TASK-700: OCR Backend Abstraction Layer
"""
import pytest

from parrot_loaders.ocr.models import LayoutLine, LayoutResult, OCRBlock


class TestOCRBlock:
    """Tests for the OCRBlock dataclass."""

    def test_creation(self):
        """OCRBlock can be created with required fields."""
        block = OCRBlock(text="hello", bbox=(10, 20, 100, 40), confidence=0.95)
        assert block.text == "hello"
        assert block.bbox == (10, 20, 100, 40)
        assert block.confidence == 0.95
        assert block.font_size_estimate is None

    def test_bbox_tuple(self):
        """Bounding box has exactly 4 elements."""
        block = OCRBlock(text="x", bbox=(0, 0, 50, 50), confidence=0.8)
        assert len(block.bbox) == 4

    def test_font_size_estimate_optional(self):
        """font_size_estimate defaults to None and can be set."""
        block_no_font = OCRBlock(text="a", bbox=(0, 0, 10, 10), confidence=0.9)
        assert block_no_font.font_size_estimate is None

        block_with_font = OCRBlock(
            text="A", bbox=(0, 0, 50, 50), confidence=0.9, font_size_estimate=50.0
        )
        assert block_with_font.font_size_estimate == 50.0

    def test_bbox_coordinates(self):
        """BBox stores (x1, y1, x2, y2) format correctly."""
        block = OCRBlock(text="test", bbox=(10, 20, 200, 40), confidence=0.9)
        x1, y1, x2, y2 = block.bbox
        assert x1 == 10
        assert y1 == 20
        assert x2 == 200
        assert y2 == 40


class TestLayoutLine:
    """Tests for the LayoutLine dataclass."""

    def test_creation(self):
        """LayoutLine can be created with required fields."""
        block = OCRBlock(text="hello", bbox=(10, 20, 100, 40), confidence=0.95)
        line = LayoutLine(blocks=[block], y_center=30.0)
        assert len(line.blocks) == 1
        assert line.y_center == 30.0
        assert line.is_header is False

    def test_header_flag(self):
        """is_header can be set to True."""
        block = OCRBlock(text="TITLE", bbox=(10, 10, 200, 50), confidence=0.98)
        line = LayoutLine(blocks=[block], y_center=30.0, is_header=True)
        assert line.is_header is True


class TestLayoutResult:
    """Tests for the LayoutResult dataclass."""

    def test_creation(self):
        """LayoutResult can be created with required fields."""
        block = OCRBlock(text="hello", bbox=(10, 20, 100, 40), confidence=0.95)
        line = LayoutLine(blocks=[block], y_center=30.0)
        result = LayoutResult(lines=[line], avg_confidence=0.95)
        assert len(result.lines) == 1
        assert result.avg_confidence == 0.95
        assert result.tables == []
        assert result.columns_detected == 1

    def test_fields(self):
        """LayoutResult has all required fields from spec."""
        result = LayoutResult(lines=[], avg_confidence=0.0)
        assert hasattr(result, "lines")
        assert hasattr(result, "tables")
        assert hasattr(result, "columns_detected")
        assert hasattr(result, "avg_confidence")


class TestGetOCRBackend:
    """Tests for the get_ocr_backend factory function."""

    def test_auto_returns_backend_or_raises(self):
        """get_ocr_backend('auto') returns a backend or raises ImportError."""
        from parrot_loaders.ocr import get_ocr_backend

        try:
            backend = get_ocr_backend("auto")
            assert hasattr(backend, "extract"), "Backend must have extract() method"
        except ImportError as exc:
            pytest.skip(f"No OCR backend available: {exc}")

    def test_invalid_backend_raises_value_error(self):
        """Unknown backend name raises ValueError with 'Unknown' in message."""
        from parrot_loaders.ocr import get_ocr_backend

        with pytest.raises(ValueError, match="Unknown"):
            get_ocr_backend("nonexistent_backend")

    def test_invalid_backend_message_lists_options(self):
        """ValueError message lists valid backend options."""
        from parrot_loaders.ocr import get_ocr_backend

        with pytest.raises(ValueError) as exc_info:
            get_ocr_backend("bad_name")
        msg = str(exc_info.value)
        assert "paddleocr" in msg or "tesseract" in msg or "easyocr" in msg

    def test_imports(self):
        """Core exports importable from parrot_loaders.ocr."""
        from parrot_loaders.ocr import (  # noqa: F401
            LayoutLine,
            LayoutResult,
            OCRBackend,
            OCRBlock,
            get_ocr_backend,
        )
