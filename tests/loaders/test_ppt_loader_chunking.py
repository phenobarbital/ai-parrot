"""Tests for PowerPointLoader full_document mode (TASK-639).

Verifies:
- full_document=True returns 1 Document per file
- Slides separated by horizontal rules (\\n\\n---\\n\\n)
- Metadata includes total_slides
- full_document=False preserves per-slide behavior
"""
import pytest
from pathlib import PurePath
from unittest.mock import patch, MagicMock, PropertyMock
from parrot_loaders.ppt import PowerPointLoader
from parrot.loaders.abstract import AbstractLoader


class TestPowerPointLoaderFullDocument:
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_full_document_default_true(self, mock_device, mock_llm):
        """PowerPointLoader inherits full_document=True from AbstractLoader."""
        loader = PowerPointLoader(backend="pptx")
        assert loader.full_document is True

    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_full_document_false_override(self, mock_device, mock_llm):
        """PowerPointLoader can be created with full_document=False."""
        loader = PowerPointLoader(backend="pptx", full_document=False)
        assert loader.full_document is False

    @pytest.mark.asyncio
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    async def test_full_document_returns_single_doc(self, mock_device, mock_llm):
        """full_document=True returns 1 Document per PPTX file."""
        loader = PowerPointLoader(backend="pptx")

        # Mock _process_pptx_content to return fake slide data
        fake_slides = [
            {
                "slide_number": 1,
                "slide_id": 1,
                "title": "Introduction",
                "content": "Welcome to the presentation.",
                "notes": "",
                "has_title": True,
            },
            {
                "slide_number": 2,
                "slide_id": 2,
                "title": "Main Topic",
                "content": "Here is the main content of the talk.",
                "notes": "Speaker notes here.",
                "has_title": True,
            },
            {
                "slide_number": 3,
                "slide_id": 3,
                "title": "Conclusion",
                "content": "Thank you for attending.",
                "notes": "",
                "has_title": True,
            },
        ]
        loader._process_pptx_content = MagicMock(return_value=fake_slides)

        docs = await loader._load(PurePath("/fake/test.pptx"))

        # Should return 1 document in full_document mode
        assert len(docs) == 1
        # Content should contain all slides
        content = docs[0].page_content
        assert "Introduction" in content
        assert "Main Topic" in content
        assert "Conclusion" in content

    @pytest.mark.asyncio
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    async def test_slides_separated_by_hr(self, mock_device, mock_llm):
        """Slides in full document are separated by horizontal rules."""
        loader = PowerPointLoader(backend="pptx")

        fake_slides = [
            {
                "slide_number": 1,
                "slide_id": 1,
                "title": "Slide One",
                "content": "Content one.",
                "notes": "",
                "has_title": True,
            },
            {
                "slide_number": 2,
                "slide_id": 2,
                "title": "Slide Two",
                "content": "Content two.",
                "notes": "",
                "has_title": True,
            },
        ]
        loader._process_pptx_content = MagicMock(return_value=fake_slides)

        docs = await loader._load(PurePath("/fake/test.pptx"))

        assert len(docs) == 1
        # Check for horizontal rule separator
        assert "\n\n---\n\n" in docs[0].page_content

    @pytest.mark.asyncio
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    async def test_metadata_includes_total_slides(self, mock_device, mock_llm):
        """Document metadata includes total_slides field."""
        loader = PowerPointLoader(backend="pptx")

        fake_slides = [
            {
                "slide_number": i + 1,
                "slide_id": i + 1,
                "title": f"Slide {i + 1}",
                "content": f"Content for slide {i + 1}.",
                "notes": "",
                "has_title": True,
            }
            for i in range(4)
        ]
        loader._process_pptx_content = MagicMock(return_value=fake_slides)

        docs = await loader._load(PurePath("/fake/test.pptx"))

        assert len(docs) == 1
        doc_meta = docs[0].metadata.get("document_meta", {})
        assert doc_meta.get("total_slides") == 4

    @pytest.mark.asyncio
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    async def test_full_document_false_returns_per_slide(self, mock_device, mock_llm):
        """full_document=False preserves per-slide behavior."""
        loader = PowerPointLoader(backend="pptx", full_document=False)

        fake_slides = [
            {
                "slide_number": 1,
                "slide_id": 1,
                "title": "Slide One",
                "content": "Content for slide one with enough text to pass.",
                "notes": "",
                "has_title": True,
            },
            {
                "slide_number": 2,
                "slide_id": 2,
                "title": "Slide Two",
                "content": "Content for slide two with enough text to pass.",
                "notes": "",
                "has_title": True,
            },
        ]
        loader._process_pptx_content = MagicMock(return_value=fake_slides)

        docs = await loader._load(PurePath("/fake/test.pptx"))

        # Should return per-slide documents
        assert len(docs) == 2
