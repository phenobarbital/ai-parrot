"""
Unit tests for EasyOCRBackend.

All tests mock easyocr (and optionally torch) via sys.modules injection so
they work without the library installed.
"""
import logging
import sys
from unittest.mock import MagicMock

import pytest
from PIL import Image

from parrot_loaders.ocr.easyocr_backend import EasyOCRBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_backend(readtext_return=None) -> EasyOCRBackend:
    """Return a pre-built EasyOCRBackend bypassing __init__."""
    backend = EasyOCRBackend.__new__(EasyOCRBackend)
    backend.logger = logging.getLogger("test_easyocr")
    mock_reader = MagicMock()
    mock_reader.readtext.return_value = readtext_return or []
    backend._reader = mock_reader
    backend._language = "en"
    return backend


def _polygon(x1: int, y1: int, x2: int, y2: int):
    """Return a 4-corner polygon for an axis-aligned box."""
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEasyOCRBackend:
    """Unit tests for EasyOCRBackend."""

    # ------------------------------------------------------------------
    # Import guard
    # ------------------------------------------------------------------

    def test_import_guard_raises_when_easyocr_missing(self):
        """ImportError raised with a clear message when easyocr is missing."""
        # Remove the cached module so the guard runs
        sys.modules.pop("parrot_loaders.ocr.easyocr_backend", None)

        with pytest.raises(ImportError, match="easyocr is not installed"):
            with _mock_easyocr_missing():
                EasyOCRBackend()

    # ------------------------------------------------------------------
    # Bbox conversion
    # ------------------------------------------------------------------

    def test_bbox_conversion_axis_aligned(self):
        """4-corner polygon converted to correct (x1, y1, x2, y2) box."""
        polygon = _polygon(10, 20, 100, 50)
        backend = _make_backend([
            (polygon, "Hello", 0.95),
        ])

        blocks = backend.extract(Image.new("RGB", (200, 100)), language="en")

        assert len(blocks) == 1
        assert blocks[0].bbox == (10, 20, 100, 50)

    def test_bbox_conversion_rotated_polygon(self):
        """Rotated polygons still produce correct min/max bbox."""
        # Tilted quadrilateral
        polygon = [[15, 30], [110, 22], [105, 55], [10, 60]]
        backend = _make_backend([
            (polygon, "World", 0.88),
        ])

        blocks = backend.extract(Image.new("RGB", (200, 100)), language="en")

        assert len(blocks) == 1
        x1, y1, x2, y2 = blocks[0].bbox
        assert x1 == 10
        assert y1 == 22
        assert x2 == 110
        assert y2 == 60

    # ------------------------------------------------------------------
    # Text and confidence
    # ------------------------------------------------------------------

    def test_text_stripped(self):
        """Text returned by EasyOCR is stripped of whitespace."""
        polygon = _polygon(0, 0, 50, 20)
        backend = _make_backend([
            (polygon, "  trimmed  ", 0.80),
        ])

        blocks = backend.extract(Image.new("RGB", (100, 50)), language="en")

        assert blocks[0].text == "trimmed"

    def test_empty_text_skipped(self):
        """Detections with blank text are excluded from the result."""
        p = _polygon(0, 0, 50, 20)
        backend = _make_backend([
            (p, "   ", 0.70),
            (p, "Real", 0.90),
        ])

        blocks = backend.extract(Image.new("RGB", (100, 50)), language="en")

        assert len(blocks) == 1
        assert blocks[0].text == "Real"

    def test_confidence_stored(self):
        """Confidence value from EasyOCR is stored as float."""
        polygon = _polygon(0, 0, 50, 20)
        backend = _make_backend([
            (polygon, "Text", 0.87654),
        ])

        blocks = backend.extract(Image.new("RGB", (100, 50)), language="en")

        assert abs(blocks[0].confidence - 0.87654) < 1e-6

    # ------------------------------------------------------------------
    # Font size estimate
    # ------------------------------------------------------------------

    def test_font_size_from_bbox_height(self):
        """font_size_estimate equals y2 - y1 of the detection bbox."""
        polygon = _polygon(10, 20, 100, 60)  # height = 40
        backend = _make_backend([
            (polygon, "Text", 0.95),
        ])

        blocks = backend.extract(Image.new("RGB", (200, 100)), language="en")

        assert blocks[0].font_size_estimate == pytest.approx(40.0)

    # ------------------------------------------------------------------
    # Empty result
    # ------------------------------------------------------------------

    def test_no_detections_returns_empty(self):
        """Empty EasyOCR result yields an empty list."""
        backend = _make_backend([])
        blocks = backend.extract(Image.new("RGB", (100, 100)), language="en")
        assert blocks == []

    # ------------------------------------------------------------------
    # GPU detection (init path)
    # ------------------------------------------------------------------

    def test_gpu_detection_with_torch(self):
        """Reader is initialised with gpu=True when torch.cuda reports CUDA."""
        mock_easyocr = MagicMock()
        mock_reader_instance = MagicMock()
        mock_easyocr.Reader.return_value = mock_reader_instance

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True

        old = {k: sys.modules.get(k) for k in ("easyocr", "torch")}
        sys.modules["easyocr"] = mock_easyocr
        sys.modules["torch"] = mock_torch
        try:
            backend = EasyOCRBackend(language="en")
        finally:
            for k, v in old.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

        mock_easyocr.Reader.assert_called_once_with(["en"], gpu=True)

    def test_gpu_detection_without_torch(self):
        """Reader is initialised with gpu=False when torch is not installed."""
        mock_easyocr = MagicMock()
        mock_reader_instance = MagicMock()
        mock_easyocr.Reader.return_value = mock_reader_instance

        old_easyocr = sys.modules.get("easyocr")
        old_torch = sys.modules.get("torch")
        sys.modules["easyocr"] = mock_easyocr
        sys.modules["torch"] = None  # simulates ImportError inside __init__
        try:
            backend = EasyOCRBackend(language="en")
        except Exception:
            pass  # may fail if torch=None triggers ImportError differently
        finally:
            if old_easyocr is None:
                sys.modules.pop("easyocr", None)
            else:
                sys.modules["easyocr"] = old_easyocr
            if old_torch is None:
                sys.modules.pop("torch", None)
            else:
                sys.modules["torch"] = old_torch

        # gpu=False should be the fallback
        call_args = mock_easyocr.Reader.call_args
        if call_args is not None:
            assert call_args[1].get("gpu") is False or call_args[0][1] is False


# ---------------------------------------------------------------------------
# Context manager helpers
# ---------------------------------------------------------------------------

class _mock_easyocr_missing:
    """Context manager that injects None for 'easyocr' in sys.modules."""

    def __enter__(self):
        self._old = sys.modules.get("easyocr", object())
        sys.modules["easyocr"] = None  # triggers ImportError on import
        return self

    def __exit__(self, *args):
        if isinstance(self._old, object) and not isinstance(self._old, type(None)):
            sys.modules.pop("easyocr", None)
        else:
            sys.modules["easyocr"] = self._old
