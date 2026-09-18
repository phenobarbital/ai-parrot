"""Tests for MSWordLoader double-chunking fix (TASK-638).

Verifies:
- _load() returns 1 Document per file (not pre-chunked)
- No reference to markdown_splitter.split_text() in _load()
- Document content includes full markdown
- Metadata preserved (author, version, title)
- No context header in page_content (f0f09dc22: it lives in metadata only)
"""
import pytest
from pathlib import PurePath

# python-docx ships with the ai-parrot-loaders[pdf|documents] extras only.
pytest.importorskip("docx")
from unittest.mock import patch, MagicMock, AsyncMock
from parrot_loaders.docx import MSWordLoader
from parrot.loaders.abstract import AbstractLoader


class TestMSWordLoaderFix:
    @pytest.mark.asyncio
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    async def test_load_returns_single_document(self, mock_device, mock_llm, tmp_path):
        """_load() returns 1 Document, not pre-chunked Documents."""
        import docx as python_docx
        # Create a minimal .docx test file
        doc = python_docx.Document()
        doc.add_heading('Test Document', 0)
        doc.add_paragraph(
            'This is the first paragraph with enough content to be meaningful. '
            'It has multiple sentences that provide context and substance.'
        )
        doc.add_paragraph(
            'This is the second paragraph with additional content. '
            'More sentences here to make the document realistic.'
        )
        doc.add_paragraph(
            'This is the third paragraph. It adds even more content '
            'to ensure the document has substance for testing purposes.'
        )
        docx_path = tmp_path / "test.docx"
        doc.save(str(docx_path))

        loader = MSWordLoader(source=docx_path)
        docs = await loader._load(PurePath(docx_path))

        # Should return exactly 1 Document (no pre-chunking)
        assert len(docs) == 1

    @pytest.mark.asyncio
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    async def test_document_contains_full_content(self, mock_device, mock_llm, tmp_path):
        """Document contains the full markdown content."""
        import docx as python_docx
        doc = python_docx.Document()
        doc.add_heading('My Title', 0)
        doc.add_paragraph('First paragraph content.')
        doc.add_paragraph('Second paragraph content.')
        docx_path = tmp_path / "test_content.docx"
        doc.save(str(docx_path))

        loader = MSWordLoader(source=docx_path)
        docs = await loader._load(PurePath(docx_path))

        assert len(docs) == 1
        content = docs[0].page_content
        # Content should have both paragraphs (not split)
        assert 'First paragraph' in content
        assert 'Second paragraph' in content

    @pytest.mark.asyncio
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    async def test_no_context_header_in_content(self, mock_device, mock_llm, tmp_path):
        """File name / doctype live in metadata, not page_content.

        f0f09dc22 stopped prepending the context header because it polluted
        the embeddings.
        """
        import docx as python_docx
        doc = python_docx.Document()
        doc.add_paragraph('Some content.')
        docx_path = tmp_path / "test_header.docx"
        doc.save(str(docx_path))

        loader = MSWordLoader(source=docx_path)
        docs = await loader._load(PurePath(docx_path))

        assert len(docs) == 1
        content = docs[0].page_content
        assert 'Some content.' in content
        assert 'File Name:' not in content
        assert 'Document Type:' not in content
        assert docs[0].metadata['source'] == 'test_header.docx'
        assert docs[0].metadata['type'] == loader.doctype

    @pytest.mark.asyncio
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    async def test_metadata_preserved(self, mock_device, mock_llm, tmp_path):
        """Document metadata is present."""
        import docx as python_docx
        doc = python_docx.Document()
        doc.core_properties.author = "Test Author"
        doc.core_properties.title = "Test Title"
        doc.add_paragraph('Some content here.')
        docx_path = tmp_path / "test_meta.docx"
        doc.save(str(docx_path))

        loader = MSWordLoader(source=docx_path)
        docs = await loader._load(PurePath(docx_path))

        assert len(docs) == 1
        metadata = docs[0].metadata
        # TASK-857 (d31959725): title is canonical document_meta; author is a
        # loader-specific extra at the top level.
        assert metadata['document_meta'].get('title') == 'Test Title'
        assert metadata.get('author') == 'Test Author'

    def test_no_split_text_in_load(self):
        """Verify _load() source code doesn't call markdown_splitter.split_text()."""
        import inspect
        source = inspect.getsource(MSWordLoader._load)
        assert 'markdown_splitter.split_text' not in source
        assert 'for chunk in' not in source
