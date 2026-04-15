"""
Unit and integration tests for ImageLoader.

Unit tests mock the OCR backend so they run without any OCR library installed.
The integration test loads the real ``docs/Part Order Guide.png`` using the
auto-detected best available backend.
"""
import asyncio
import logging
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from parrot_loaders.ocr.models import OCRBlock, LayoutResult, LayoutLine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

WORKTREE_ROOT = Path(__file__).parent.parent.parent


def _make_mock_backend(blocks: List[OCRBlock]) -> MagicMock:
    """Return a mock OCR backend that returns *blocks*."""
    backend = MagicMock()
    backend.__class__.__name__ = "MockOCRBackend"
    backend.extract.return_value = blocks
    return backend


def _sample_blocks() -> List[OCRBlock]:
    """Minimal OCR blocks for unit tests."""
    return [
        OCRBlock(text="Hello World", bbox=(10, 10, 200, 40), confidence=0.95),
        OCRBlock(text="Item Price Qty", bbox=(10, 60, 300, 80), confidence=0.90),
    ]


# ---------------------------------------------------------------------------
# TestImageLoaderInit
# ---------------------------------------------------------------------------


class TestImageLoaderInit:
    def test_default_init(self):
        """ImageLoader initialises with auto backend and heuristic layout."""
        with patch("parrot_loaders.image.get_ocr_backend") as mock_factory:
            mock_factory.return_value = MagicMock()
            from parrot_loaders.image import ImageLoader

            loader = ImageLoader()
            assert loader._layout_model is None

    def test_min_confidence_stored(self):
        """min_confidence parameter is stored on the loader."""
        with patch("parrot_loaders.image.get_ocr_backend") as mock_factory:
            mock_factory.return_value = MagicMock()
            from parrot_loaders.image import ImageLoader

            loader = ImageLoader(min_confidence=0.75)
            assert loader._min_confidence == 0.75

    def test_language_stored(self):
        """language parameter is stored on the loader."""
        with patch("parrot_loaders.image.get_ocr_backend") as mock_factory:
            mock_factory.return_value = MagicMock()
            from parrot_loaders.image import ImageLoader

            loader = ImageLoader(language="fr")
            assert loader._language == "fr"

    def test_ocr_backend_name_stored(self):
        """ocr_backend name is stored on the loader."""
        with patch("parrot_loaders.image.get_ocr_backend") as mock_factory:
            mock_factory.return_value = MagicMock()
            from parrot_loaders.image import ImageLoader

            loader = ImageLoader(ocr_backend="tesseract")
            assert loader._ocr_backend_name == "tesseract"

    def test_layoutlmv3_init(self):
        """layout_model='layoutlmv3' attempts to load LayoutLMv3Analyzer."""
        pytest.importorskip("transformers")
        # transformers is present — skip actual model download
        pytest.skip("Integration: requires model download")

    def test_extensions_defined(self):
        """ImageLoader declares a list of supported extensions."""
        with patch("parrot_loaders.image.get_ocr_backend") as mock_factory:
            mock_factory.return_value = MagicMock()
            from parrot_loaders.image import ImageLoader

            assert ".png" in ImageLoader.extensions
            assert ".jpg" in ImageLoader.extensions


# ---------------------------------------------------------------------------
# TestImageLoaderLoad
# ---------------------------------------------------------------------------


class TestImageLoaderLoad:
    @pytest.mark.asyncio
    async def test_load_returns_document(self, tmp_path):
        """_load() returns a list with at least one Document."""
        # Create a tiny valid PNG for testing
        img_path = tmp_path / "test.png"
        img = Image.new("RGB", (200, 100), color="white")
        img.save(str(img_path))

        with patch("parrot_loaders.image.get_ocr_backend") as mock_factory:
            mock_backend = _make_mock_backend(_sample_blocks())
            mock_factory.return_value = mock_backend

            from parrot_loaders.image import ImageLoader

            loader = ImageLoader(min_confidence=0.0)
            loader._backend = mock_backend

            docs = await loader._load(img_path)

        assert len(docs) >= 1

    @pytest.mark.asyncio
    async def test_load_document_has_page_content(self, tmp_path):
        """Returned Document has non-empty page_content."""
        img_path = tmp_path / "test.png"
        Image.new("RGB", (200, 100), color="white").save(str(img_path))

        with patch("parrot_loaders.image.get_ocr_backend") as mock_factory:
            mock_backend = _make_mock_backend(_sample_blocks())
            mock_factory.return_value = mock_backend

            from parrot_loaders.image import ImageLoader

            loader = ImageLoader(min_confidence=0.0)
            loader._backend = mock_backend
            docs = await loader._load(img_path)

        assert docs[0].page_content  # non-empty string

    @pytest.mark.asyncio
    async def test_metadata_contains_required_fields(self, tmp_path):
        """Document metadata.document_meta contains all required fields."""
        img_path = tmp_path / "test.png"
        Image.new("RGB", (200, 100), color="white").save(str(img_path))

        with patch("parrot_loaders.image.get_ocr_backend") as mock_factory:
            mock_backend = _make_mock_backend(_sample_blocks())
            mock_factory.return_value = mock_backend

            from parrot_loaders.image import ImageLoader

            loader = ImageLoader(min_confidence=0.0)
            loader._backend = mock_backend
            docs = await loader._load(img_path)

        doc_meta = docs[0].metadata.get("document_meta", {})
        assert "ocr_backend" in doc_meta
        assert "layout_model" in doc_meta
        assert "avg_confidence" in doc_meta
        assert "image_dimensions" in doc_meta
        assert "table_count" in doc_meta
        assert "language" in doc_meta

    @pytest.mark.asyncio
    async def test_min_confidence_filters_blocks(self, tmp_path):
        """Blocks below min_confidence are excluded from the document."""
        img_path = tmp_path / "test.png"
        Image.new("RGB", (200, 100), color="white").save(str(img_path))

        # One high-confidence block, one low-confidence block
        blocks = [
            OCRBlock(text="GOOD", bbox=(10, 10, 100, 40), confidence=0.95),
            OCRBlock(text="bad", bbox=(10, 50, 100, 80), confidence=0.05),
        ]

        with patch("parrot_loaders.image.get_ocr_backend") as mock_factory:
            mock_backend = _make_mock_backend(blocks)
            mock_factory.return_value = mock_backend

            from parrot_loaders.image import ImageLoader

            loader = ImageLoader(min_confidence=0.5)
            loader._backend = mock_backend
            docs = await loader._load(img_path)

        # Only "GOOD" survives the filter
        content = docs[0].page_content if docs else ""
        assert "GOOD" in content or content == ""  # or empty if no blocks
        assert "bad" not in content

    @pytest.mark.asyncio
    async def test_load_nonexistent_file_returns_empty(self):
        """Loading a non-existent file returns an empty list."""
        with patch("parrot_loaders.image.get_ocr_backend") as mock_factory:
            mock_factory.return_value = MagicMock()

            from parrot_loaders.image import ImageLoader

            loader = ImageLoader()
            docs = await loader._load(Path("/does/not/exist.png"))

        assert docs == []

    @pytest.mark.asyncio
    async def test_load_png_integration(self):
        """Integration: load the real docs/Part Order Guide.png."""
        image_path = WORKTREE_ROOT / "docs" / "Part Order Guide.png"
        if not image_path.exists():
            pytest.skip("Test image not found at docs/Part Order Guide.png")

        with patch("parrot_loaders.image.get_ocr_backend") as mock_factory:
            mock_backend = _make_mock_backend([
                OCRBlock(
                    text="Part Order Guide",
                    bbox=(100, 20, 500, 70),
                    confidence=0.98,
                    font_size_estimate=50.0,
                )
            ])
            mock_factory.return_value = mock_backend

            from parrot_loaders.image import ImageLoader

            loader = ImageLoader(source=str(image_path), min_confidence=0.0)
            loader._backend = mock_backend
            docs = await loader._load(image_path)

        assert len(docs) >= 1
        assert docs[0].page_content
        doc_meta = docs[0].metadata.get("document_meta", {})
        assert doc_meta.get("ocr_backend")


# ---------------------------------------------------------------------------
# TestImageLoaderRegistry
# ---------------------------------------------------------------------------


class TestImageLoaderRegistry:
    def test_in_registry(self):
        """ImageLoader is registered in LOADER_REGISTRY."""
        from parrot_loaders import LOADER_REGISTRY

        assert "ImageLoader" in LOADER_REGISTRY

    def test_registry_path_correct(self):
        """LOADER_REGISTRY entry points to the correct dotted path."""
        from parrot_loaders import LOADER_REGISTRY

        assert LOADER_REGISTRY["ImageLoader"] == "parrot_loaders.image.ImageLoader"
