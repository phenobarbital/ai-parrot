"""
Unit tests for TesseractBackend.

All tests mock pytesseract so they work without a Tesseract binary installed.
The TesseractBackend lazily imports pytesseract inside each method, so we
inject the mock via ``sys.modules``.
"""
import logging
import sys
from typing import Dict, List
from unittest.mock import MagicMock

import pytest
from PIL import Image

# Pre-import the module so the class is available for __new__ usage.
# We always inject a mock into sys.modules["pytesseract"] before calling
# anything that touches the real binary.
from parrot_loaders.ocr.tesseract import TesseractBackend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pytesseract_mock(data: Dict[str, List]) -> MagicMock:
    """Return a minimal pytesseract mock configured with *data*."""
    mock_pt = MagicMock()
    mock_pt.get_tesseract_version.return_value = "5.0.0"
    mock_pt.Output = MagicMock()
    mock_pt.Output.DICT = "dict"
    mock_pt.image_to_data.return_value = data
    return mock_pt


def _sample_data() -> Dict[str, List]:
    """Two words in block1/par1 and one word in block2/par1."""
    return {
        "text":      ["Hello",  "World",  "Foo"],
        "conf":      [95,        90,        85],
        "block_num": [1,         1,         2],
        "par_num":   [1,         1,         1],
        "left":      [10,        80,        200],
        "top":       [20,        20,         50],
        "width":     [60,        50,         40],
        "height":    [20,        20,         18],
    }


def _make_backend() -> TesseractBackend:
    """Create a TesseractBackend bypassing __init__ (skips binary check)."""
    backend = TesseractBackend.__new__(TesseractBackend)
    backend._lang = "en"
    backend.logger = logging.getLogger("test_tesseract")
    return backend


def _inject(mock: MagicMock) -> None:
    """Put *mock* into sys.modules so lazily-imported pytesseract uses it."""
    sys.modules["pytesseract"] = mock


def _eject() -> None:
    """Remove the pytesseract mock from sys.modules."""
    sys.modules.pop("pytesseract", None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTesseractBackend:
    """Unit tests for TesseractBackend."""

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def test_binary_detection_raises_import_error(self):
        """ImportError with a clear message when tesseract binary is missing."""
        bad_mock = MagicMock()
        bad_mock.get_tesseract_version.side_effect = Exception("not found")
        _inject(bad_mock)
        try:
            with pytest.raises(ImportError, match="tesseract binary not found"):
                TesseractBackend()
        finally:
            _eject()

    def test_init_success(self):
        """_lang attribute is set when __init__ bypassed."""
        backend = _make_backend()
        assert backend._lang == "en"

    # ------------------------------------------------------------------
    # Word grouping
    # ------------------------------------------------------------------

    def test_word_grouping(self):
        """Words sharing (block_num, par_num) are merged into one OCRBlock."""
        mock_pt = _make_pytesseract_mock(_sample_data())
        _inject(mock_pt)
        try:
            backend = _make_backend()
            blocks = backend.extract(Image.new("RGB", (300, 100)), language="en")
        finally:
            _eject()

        assert len(blocks) == 2
        texts = {b.text for b in blocks}
        assert "Hello World" in texts
        assert "Foo" in texts

    # ------------------------------------------------------------------
    # Bounding-box merging
    # ------------------------------------------------------------------

    def test_bbox_merging(self):
        """Block bbox spans the union of all word bboxes in the same group."""
        mock_pt = _make_pytesseract_mock(_sample_data())
        _inject(mock_pt)
        try:
            backend = _make_backend()
            blocks = backend.extract(Image.new("RGB", (300, 100)), language="en")
        finally:
            _eject()

        merged = next(b for b in blocks if "Hello" in b.text)
        x1, y1, x2, y2 = merged.bbox
        # left=10, top=20; right-of-World=80+50=130, bottom=20+20=40
        assert x1 == 10
        assert y1 == 20
        assert x2 == 130
        assert y2 == 40

    # ------------------------------------------------------------------
    # Confidence averaging
    # ------------------------------------------------------------------

    def test_confidence_averaging(self):
        """Block confidence is the mean of per-word confidences (scaled 0–1)."""
        mock_pt = _make_pytesseract_mock(_sample_data())
        _inject(mock_pt)
        try:
            backend = _make_backend()
            blocks = backend.extract(Image.new("RGB", (300, 100)), language="en")
        finally:
            _eject()

        merged = next(b for b in blocks if "Hello" in b.text)
        # Hello=95 → 0.95, World=90 → 0.90; avg = 0.925
        assert abs(merged.confidence - 0.925) < 1e-9

    # ------------------------------------------------------------------
    # Language mapping
    # ------------------------------------------------------------------

    def test_language_mapping_en_to_eng(self):
        """'en' is translated to 'eng' before calling pytesseract."""
        mock_pt = _make_pytesseract_mock(_sample_data())
        _inject(mock_pt)
        try:
            backend = _make_backend()
            backend.extract(Image.new("RGB", (300, 100)), language="en")
        finally:
            _eject()

        call_kwargs = mock_pt.image_to_data.call_args
        lang_used = call_kwargs[1].get("lang")
        assert lang_used == "eng"

    def test_language_mapping_unknown_passthrough(self):
        """Unknown language codes are passed unchanged to pytesseract."""
        mock_pt = _make_pytesseract_mock(_sample_data())
        _inject(mock_pt)
        try:
            backend = _make_backend()
            backend.extract(Image.new("RGB", (300, 100)), language="xyx")
        finally:
            _eject()

        call_kwargs = mock_pt.image_to_data.call_args
        lang_used = call_kwargs[1].get("lang")
        assert lang_used == "xyx"

    def test_language_map_contains_standard_codes(self):
        """LANGUAGE_MAP has correct entries for common ISO 639-1 codes."""
        assert TesseractBackend.LANGUAGE_MAP["en"] == "eng"
        assert TesseractBackend.LANGUAGE_MAP["fr"] == "fra"
        assert TesseractBackend.LANGUAGE_MAP["de"] == "deu"
        assert TesseractBackend.LANGUAGE_MAP["zh"] == "chi_sim"

    # ------------------------------------------------------------------
    # Skipping invalid entries
    # ------------------------------------------------------------------

    def test_skips_conf_minus_one(self):
        """Entries with conf==-1 (layout markers) are excluded."""
        data = {
            "text":      ["",    "Real"],
            "conf":      [-1,    88],
            "block_num": [1,     1],
            "par_num":   [1,     1],
            "left":      [0,     10],
            "top":       [0,     5],
            "width":     [100,   30],
            "height":    [10,    12],
        }
        mock_pt = _make_pytesseract_mock(data)
        _inject(mock_pt)
        try:
            backend = _make_backend()
            blocks = backend.extract(Image.new("RGB", (200, 50)), language="en")
        finally:
            _eject()

        assert len(blocks) == 1
        assert blocks[0].text == "Real"

    def test_empty_image_returns_no_blocks(self):
        """Completely empty Tesseract output yields an empty list."""
        data: Dict[str, List] = {
            "text": [], "conf": [], "block_num": [], "par_num": [],
            "left": [], "top": [], "width": [], "height": [],
        }
        mock_pt = _make_pytesseract_mock(data)
        _inject(mock_pt)
        try:
            backend = _make_backend()
            blocks = backend.extract(Image.new("RGB", (100, 100)), language="en")
        finally:
            _eject()

        assert blocks == []
