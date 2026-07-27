"""Tests for MSWordLoader NoneType crash fix (FEAT-385 / NAV-9269).

Verifies:
- Paragraphs with style=None are treated as plain body text (no crash).
- Heading paragraphs still produce Markdown heading syntax.
- List paragraphs still produce Markdown list syntax.
- A document mixing None-style paragraphs with valid ones loads without error.
"""
import pytest
from pathlib import PurePath
from unittest.mock import MagicMock, patch
from parrot_loaders.docx import MSWordLoader
from parrot.loaders.abstract import AbstractLoader


@pytest.fixture
def mock_paragraph_none_style():
    """Return a mock docx Paragraph whose .style is None."""
    para = MagicMock()
    para.style = None
    para.text = "Body paragraph without style"
    return para


@pytest.fixture
def mock_paragraph_heading():
    """Return a mock docx Paragraph with a Heading 1 style."""
    para = MagicMock()
    para.style.name = "Heading 1"
    para.text = "My Heading"
    return para


@pytest.fixture
def mock_paragraph_list():
    """Return a mock docx Paragraph with a List Bullet style."""
    para = MagicMock()
    para.style.name = "List Bullet"
    para.text = "List item text"
    return para


@pytest.fixture
def mock_paragraph_body():
    """Return a mock docx Paragraph with a Normal style."""
    para = MagicMock()
    para.style.name = "Normal"
    para.text = "Normal body text"
    return para


@pytest.fixture
def loader():
    """Return an MSWordLoader with LLM/device setup mocked out."""
    with (
        patch.object(AbstractLoader, '_setup_llm'),
        patch.object(AbstractLoader, '_setup_device'),
    ):
        return MSWordLoader(source="/tmp/fake.docx")


def _make_mock_doc(paragraphs, tables=None):
    """Build a minimal mock docx.Document with the given paragraph mocks."""
    mock_doc = MagicMock()
    mock_doc.paragraphs = paragraphs
    mock_doc.tables = tables or []
    return mock_doc


class TestNoneStyleParagraph:
    """NAV-9269: para.style is None must not crash docx_to_markdown()."""

    def test_none_style_paragraph_treated_as_body(
        self, loader, mock_paragraph_none_style
    ):
        """Para with style=None renders as plain text without raising."""
        mock_doc = _make_mock_doc([mock_paragraph_none_style])

        with patch("parrot_loaders.docx.docx.Document", return_value=mock_doc):
            result = loader.docx_to_markdown("/tmp/fake.docx")

        assert "Body paragraph without style" in result

    def test_none_style_no_attribute_error(self, loader, mock_paragraph_none_style):
        """docx_to_markdown() must not raise AttributeError for None style."""
        mock_doc = _make_mock_doc([mock_paragraph_none_style])

        with patch("parrot_loaders.docx.docx.Document", return_value=mock_doc):
            try:
                loader.docx_to_markdown("/tmp/fake.docx")
            except AttributeError as exc:
                pytest.fail(f"AttributeError raised unexpectedly: {exc}")

    def test_heading_style_still_works(self, loader, mock_paragraph_heading):
        """Heading paragraphs still produce Markdown heading syntax."""
        mock_doc = _make_mock_doc([mock_paragraph_heading])

        with patch("parrot_loaders.docx.docx.Document", return_value=mock_doc):
            result = loader.docx_to_markdown("/tmp/fake.docx")

        assert "# My Heading" in result

    def test_list_style_still_works(self, loader, mock_paragraph_list):
        """List paragraphs still produce Markdown list syntax."""
        mock_doc = _make_mock_doc([mock_paragraph_list])

        with patch("parrot_loaders.docx.docx.Document", return_value=mock_doc):
            result = loader.docx_to_markdown("/tmp/fake.docx")

        assert "- List item text" in result

    def test_mixed_doc_with_none_style(
        self,
        loader,
        mock_paragraph_none_style,
        mock_paragraph_heading,
        mock_paragraph_body,
    ):
        """Doc with a mix of None and valid styles loads without crash."""
        paragraphs = [
            mock_paragraph_heading,
            mock_paragraph_none_style,
            mock_paragraph_body,
        ]
        mock_doc = _make_mock_doc(paragraphs)

        with patch("parrot_loaders.docx.docx.Document", return_value=mock_doc):
            result = loader.docx_to_markdown("/tmp/fake.docx")

        assert "My Heading" in result
        assert "Body paragraph without style" in result
        assert "Normal body text" in result

    @pytest.mark.asyncio
    async def test_load_succeeds_with_none_style_paragraph(
        self, loader, mock_paragraph_none_style
    ):
        """_load() returns a non-empty Document list when a paragraph has None style."""
        mock_props = MagicMock()
        mock_props.title = "Test Doc"
        mock_props.author = "Author"
        mock_props.version = "1.0"

        mock_doc = _make_mock_doc([mock_paragraph_none_style])
        mock_doc.core_properties = mock_props

        with patch("parrot_loaders.docx.docx.Document", return_value=mock_doc):
            docs = await loader._load(PurePath("/tmp/fake.docx"))

        assert len(docs) == 1
        assert "Body paragraph without style" in docs[0].page_content
