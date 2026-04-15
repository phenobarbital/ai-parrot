"""
Unit tests for LayoutLMv3Analyzer.

All tests that require the real model are skipped (marked as integration
tests).  The import-guard and bbox-rescaling tests do NOT require transformers
or torch to be installed.
"""
import sys
from unittest.mock import MagicMock

import pytest
from PIL import Image

from parrot_loaders.ocr.models import OCRBlock


# ---------------------------------------------------------------------------
# TestLayoutLMv3Analyzer
# ---------------------------------------------------------------------------


class TestLayoutLMv3Analyzer:
    """Unit tests for LayoutLMv3Analyzer."""

    # ------------------------------------------------------------------
    # Import guard
    # ------------------------------------------------------------------

    def test_import_guard_when_transformers_missing(self):
        """ImportError raised when transformers is not installed."""
        # Remove cached module so __init__ re-runs import guard
        sys.modules.pop("parrot_loaders.ocr.layoutlm", None)

        old_transformers = sys.modules.get("transformers")
        sys.modules["transformers"] = None  # type: ignore[assignment]
        try:
            from parrot_loaders.ocr.layoutlm import LayoutLMv3Analyzer

            with pytest.raises(ImportError, match="transformers"):
                LayoutLMv3Analyzer()
        finally:
            if old_transformers is None:
                sys.modules.pop("transformers", None)
            else:
                sys.modules["transformers"] = old_transformers

    def test_module_importable_without_transformers(self):
        """The module can be imported even when transformers is absent."""
        # This test just verifies the import doesn't blow up at module level
        from parrot_loaders.ocr import layoutlm  # noqa: F401

        assert hasattr(layoutlm, "LayoutLMv3Analyzer")

    # ------------------------------------------------------------------
    # Bbox rescaling (no model needed — uses __new__)
    # ------------------------------------------------------------------

    def test_bbox_rescaling_basic(self):
        """Bboxes are correctly rescaled to 0-1000 range."""
        from parrot_loaders.ocr.layoutlm import LayoutLMv3Analyzer

        analyzer = LayoutLMv3Analyzer.__new__(LayoutLMv3Analyzer)
        blocks = [
            OCRBlock(text="Title", bbox=(100, 50, 500, 100), confidence=0.95)
        ]
        rescaled = analyzer._rescale_bboxes(blocks, image_width=1000, image_height=800)
        assert all(0 <= v <= 1000 for bbox in rescaled for v in bbox)

    def test_bbox_rescaling_values(self):
        """Rescaling produces the expected integer values."""
        from parrot_loaders.ocr.layoutlm import LayoutLMv3Analyzer

        analyzer = LayoutLMv3Analyzer.__new__(LayoutLMv3Analyzer)
        blocks = [
            OCRBlock(text="Test", bbox=(200, 100, 600, 300), confidence=0.9)
        ]
        # image 1000x500 → target 1000
        # x1=200/1000*1000=200, y1=100/500*1000=200
        # x2=600/1000*1000=600, y2=300/500*1000=600
        rescaled = analyzer._rescale_bboxes(blocks, image_width=1000, image_height=500)
        assert rescaled == [[200, 200, 600, 600]]

    def test_bbox_rescaling_all_values_in_range(self):
        """All rescaled values are within [0, 1000]."""
        from parrot_loaders.ocr.layoutlm import LayoutLMv3Analyzer

        analyzer = LayoutLMv3Analyzer.__new__(LayoutLMv3Analyzer)
        blocks = [
            OCRBlock(text="A", bbox=(0, 0, 800, 600), confidence=0.9),
            OCRBlock(text="B", bbox=(400, 300, 800, 600), confidence=0.8),
        ]
        rescaled = analyzer._rescale_bboxes(blocks, image_width=800, image_height=600)
        for bbox in rescaled:
            for v in bbox:
                assert 0 <= v <= 1000

    def test_bbox_rescaling_empty_blocks(self):
        """Empty block list returns empty list."""
        from parrot_loaders.ocr.layoutlm import LayoutLMv3Analyzer

        analyzer = LayoutLMv3Analyzer.__new__(LayoutLMv3Analyzer)
        result = analyzer._rescale_bboxes([], image_width=800, image_height=600)
        assert result == []

    def test_bbox_rescaling_single_pixel(self):
        """Single pixel coordinates rescale to the expected values."""
        from parrot_loaders.ocr.layoutlm import LayoutLMv3Analyzer

        analyzer = LayoutLMv3Analyzer.__new__(LayoutLMv3Analyzer)
        blocks = [OCRBlock(text="x", bbox=(1, 1, 1, 1), confidence=0.9)]
        # 1/100 * 1000 = 10
        rescaled = analyzer._rescale_bboxes(blocks, image_width=100, image_height=100)
        assert rescaled == [[10, 10, 10, 10]]

    # ------------------------------------------------------------------
    # LABEL_MAP
    # ------------------------------------------------------------------

    def test_label_map_contains_required_keys(self):
        """LABEL_MAP contains paragraph, title, list, table, figure, caption."""
        from parrot_loaders.ocr.layoutlm import LayoutLMv3Analyzer

        required = {"paragraph", "title", "list", "table", "figure", "caption"}
        assert required <= set(LayoutLMv3Analyzer.LABEL_MAP.values())

    # ------------------------------------------------------------------
    # Integration (skipped unless transformers is available)
    # ------------------------------------------------------------------

    def test_analyze_returns_layout_result(self):
        """analyze() returns a LayoutResult (integration — skipped if no model)."""
        pytest.importorskip("transformers")
        # If we reach here, transformers is installed but we still skip
        # to avoid actually downloading the model in CI.
        pytest.skip("Integration test: requires model download")
