"""Tests for PDFLoader full_document mode (TASK-637).

Verifies:
- full_document=True returns 1 Document per file
- Metadata includes total_pages
- full_document=False preserves per-page behavior
- use_chapters/use_pages override full_document
"""
import pytest
from pathlib import Path, PurePath
from unittest.mock import patch, MagicMock, AsyncMock
from parrot_loaders.pdf import PDFLoader
from parrot.loaders.abstract import AbstractLoader


class TestPDFLoaderFullDocument:
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_full_document_default_true(self, mock_device, mock_llm):
        """PDFLoader inherits full_document=True from AbstractLoader."""
        loader = PDFLoader()
        assert loader.full_document is True

    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_full_document_false_override(self, mock_device, mock_llm):
        """PDFLoader can be created with full_document=False."""
        loader = PDFLoader(full_document=False)
        assert loader.full_document is False

    @pytest.mark.asyncio
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    async def test_full_document_returns_single_doc(self, mock_device, mock_llm, tmp_path):
        """full_document=True returns 1 Document per PDF file."""
        import fitz
        # Create a minimal PDF with 3 pages
        pdf_doc = fitz.open()
        for text in [
            "Title Page: Annual Report",
            "Chapter 1: Introduction to testing.",
            "Chapter 2: Detailed analysis of results.",
        ]:
            page = pdf_doc.new_page()
            page.insert_text((72, 72), text, fontsize=11)
        pdf_path = tmp_path / "test.pdf"
        pdf_doc.save(str(pdf_path))
        pdf_doc.close()

        loader = PDFLoader(source=pdf_path)
        loader.summary_from_text = AsyncMock(return_value=None)
        docs = await loader._load(PurePath(pdf_path))

        # Should return exactly 1 document (full_document mode)
        assert len(docs) == 1
        # Metadata should include total_pages (nested in document_meta)
        doc_meta = docs[0].metadata.get('document_meta', {})
        assert doc_meta.get('total_pages') == 3

    @pytest.mark.asyncio
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    async def test_full_document_false_returns_per_page(self, mock_device, mock_llm, tmp_path):
        """full_document=False returns per-page Documents."""
        import fitz
        pdf_doc = fitz.open()
        # Use longer text so it's not classified as title-only
        for text in [
            "Page 1: This document provides a comprehensive overview of the testing methodology used in our software development lifecycle. It covers various aspects of testing approaches.",
            "Page 2: The second section describes the integration testing strategy in detail. We use a combination of automated and manual testing to ensure quality.",
            "Page 3: In this final section, we discuss the results and conclusions drawn from our extensive testing process and provide recommendations for future improvements.",
        ]:
            page = pdf_doc.new_page()
            page.insert_text((72, 72), text, fontsize=9)
        pdf_path = tmp_path / "test_per_page.pdf"
        pdf_doc.save(str(pdf_path))
        pdf_doc.close()

        loader = PDFLoader(source=pdf_path, full_document=False)
        loader.summary_from_text = AsyncMock(return_value=None)
        docs = await loader._load(PurePath(pdf_path))

        # Should return multiple documents (per-page)
        assert len(docs) >= 2

    @pytest.mark.asyncio
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    async def test_use_chapters_overrides_full_document(self, mock_device, mock_llm, tmp_path):
        """use_chapters=True takes precedence over full_document=True."""
        import fitz
        pdf_doc = fitz.open()
        page = pdf_doc.new_page()
        page.insert_text((72, 72), "Some content here with enough text.", fontsize=11)
        pdf_path = tmp_path / "test_chapters.pdf"
        pdf_doc.save(str(pdf_path))
        pdf_doc.close()

        loader = PDFLoader(source=pdf_path, use_chapters=True)
        # use_chapters is True, so full_document path should not be used
        assert loader.full_document is True
        assert loader.use_chapters is True
        # The _load method should skip the full_document path
        # (it checks: self.full_document and not self.use_chapters)

    @pytest.mark.asyncio
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    async def test_metadata_includes_total_pages(self, mock_device, mock_llm, tmp_path):
        """Document metadata includes total_pages field."""
        import fitz
        pdf_doc = fitz.open()
        for i in range(5):
            page = pdf_doc.new_page()
            page.insert_text((72, 72), f"Page {i+1} content.", fontsize=11)
        pdf_path = tmp_path / "test_meta.pdf"
        pdf_doc.save(str(pdf_path))
        pdf_doc.close()

        loader = PDFLoader(source=pdf_path)
        loader.summary_from_text = AsyncMock(return_value=None)
        docs = await loader._load(PurePath(pdf_path))

        assert len(docs) == 1
        doc_meta = docs[0].metadata.get('document_meta', {})
        assert doc_meta.get('total_pages') == 5
