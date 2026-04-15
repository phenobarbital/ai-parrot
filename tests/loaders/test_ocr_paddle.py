"""
Unit tests for PaddleOCR Backend.

TASK-701: PaddleOCR Backend
"""
import sys
from unittest.mock import MagicMock, patch

import pytest


class TestPaddleOCRBackend:
    """Tests for the PaddleOCRBackend class."""

    def test_import_guard_raises_when_unavailable(self):
        """Clear ImportError raised when paddleocr not installed."""
        # Remove any cached module to force re-import
        mods_to_remove = [k for k in sys.modules if k.startswith("paddleocr")]
        for mod in mods_to_remove:
            del sys.modules[mod]

        with patch.dict("sys.modules", {"paddleocr": None}):
            # Also remove the cached paddle module to force re-import
            paddle_mod = sys.modules.pop(
                "parrot_loaders.ocr.paddle", None
            )
            try:
                from parrot_loaders.ocr.paddle import PaddleOCRBackend

                with pytest.raises(ImportError, match="paddleocr"):
                    PaddleOCRBackend()
            finally:
                if paddle_mod is not None:
                    sys.modules["parrot_loaders.ocr.paddle"] = paddle_mod

    def test_bbox_conversion_from_polygon(self):
        """4-point polygon converted to (x1, y1, x2, y2) axis-aligned box."""
        mock_paddle_ocr = MagicMock()
        # Polygon: top-left=(10,20), top-right=(100,25), bottom-right=(105,45), bottom-left=(8,40)
        mock_paddle_ocr.ocr.return_value = [
            [
                [
                    [[10, 20], [100, 25], [105, 45], [8, 40]],
                    ("Hello World", 0.95),
                ]
            ]
        ]

        with patch("parrot_loaders.ocr.paddle.PaddleOCRBackend.__init__") as mock_init:
            mock_init.return_value = None
            from parrot_loaders.ocr.paddle import PaddleOCRBackend
            from PIL import Image

            backend = PaddleOCRBackend.__new__(PaddleOCRBackend)
            backend._ocr = mock_paddle_ocr
            backend._language = "en"
            import logging
            backend.logger = logging.getLogger("test")

            img = Image.new("RGB", (200, 100), color="white")
            blocks = backend.extract(img)

        assert len(blocks) == 1
        block = blocks[0]
        assert block.text == "Hello World"
        assert block.bbox == (8, 20, 105, 45)  # min/max of polygon coords
        assert block.confidence == pytest.approx(0.95)

    def test_font_size_from_bbox_height(self):
        """font_size_estimate is derived from bbox height (y2 - y1)."""
        mock_paddle_ocr = MagicMock()
        mock_paddle_ocr.ocr.return_value = [
            [
                [
                    [[0, 10], [100, 10], [100, 50], [0, 50]],
                    ("Text", 0.9),
                ]
            ]
        ]

        with patch("parrot_loaders.ocr.paddle.PaddleOCRBackend.__init__") as mock_init:
            mock_init.return_value = None
            from parrot_loaders.ocr.paddle import PaddleOCRBackend
            from PIL import Image

            backend = PaddleOCRBackend.__new__(PaddleOCRBackend)
            backend._ocr = mock_paddle_ocr
            backend._language = "en"
            import logging
            backend.logger = logging.getLogger("test")

            img = Image.new("RGB", (200, 100), color="white")
            blocks = backend.extract(img)

        assert len(blocks) == 1
        assert blocks[0].font_size_estimate == pytest.approx(40.0)  # y2-y1 = 50-10 = 40

    def test_confidence_filter_removes_low_confidence(self):
        """Blocks with confidence < 0.1 are filtered out."""
        mock_paddle_ocr = MagicMock()
        mock_paddle_ocr.ocr.return_value = [
            [
                [[[0, 0], [50, 0], [50, 20], [0, 20]], ("Noise", 0.05)],
                [[[0, 30], [50, 30], [50, 50], [0, 50]], ("Real text", 0.85)],
            ]
        ]

        with patch("parrot_loaders.ocr.paddle.PaddleOCRBackend.__init__") as mock_init:
            mock_init.return_value = None
            from parrot_loaders.ocr.paddle import PaddleOCRBackend
            from PIL import Image

            backend = PaddleOCRBackend.__new__(PaddleOCRBackend)
            backend._ocr = mock_paddle_ocr
            backend._language = "en"
            import logging
            backend.logger = logging.getLogger("test")

            img = Image.new("RGB", (100, 100), color="white")
            blocks = backend.extract(img)

        assert len(blocks) == 1
        assert blocks[0].text == "Real text"

    def test_empty_result_returns_empty_list(self):
        """Empty OCR result returns empty list."""
        mock_paddle_ocr = MagicMock()
        mock_paddle_ocr.ocr.return_value = []

        with patch("parrot_loaders.ocr.paddle.PaddleOCRBackend.__init__") as mock_init:
            mock_init.return_value = None
            from parrot_loaders.ocr.paddle import PaddleOCRBackend
            from PIL import Image

            backend = PaddleOCRBackend.__new__(PaddleOCRBackend)
            backend._ocr = mock_paddle_ocr
            backend._language = "en"
            import logging
            backend.logger = logging.getLogger("test")

            img = Image.new("RGB", (100, 100), color="white")
            blocks = backend.extract(img)

        assert blocks == []

    def test_none_page_result_returns_empty_list(self):
        """None page in OCR result returns empty list."""
        mock_paddle_ocr = MagicMock()
        mock_paddle_ocr.ocr.return_value = [None]

        with patch("parrot_loaders.ocr.paddle.PaddleOCRBackend.__init__") as mock_init:
            mock_init.return_value = None
            from parrot_loaders.ocr.paddle import PaddleOCRBackend
            from PIL import Image

            backend = PaddleOCRBackend.__new__(PaddleOCRBackend)
            backend._ocr = mock_paddle_ocr
            backend._language = "en"
            import logging
            backend.logger = logging.getLogger("test")

            img = Image.new("RGB", (100, 100), color="white")
            blocks = backend.extract(img)

        assert blocks == []

    def test_language_map(self):
        """Language code mapping from ISO to PaddleOCR codes."""
        from parrot_loaders.ocr.paddle import PaddleOCRBackend

        assert PaddleOCRBackend.LANGUAGE_MAP["en"] == "en"
        assert PaddleOCRBackend.LANGUAGE_MAP["zh"] == "ch"
        assert PaddleOCRBackend.LANGUAGE_MAP["ja"] == "japan"
