"""Tests for AbstractLoader default changes (TASK-636).

Verifies the new defaults: chunk_size=2048, chunk_overlap=200,
min_chunk_size=50, full_document=True, SemanticTextSplitter as default,
and removal of token_size.
"""
import pytest
from unittest.mock import patch, MagicMock
from parrot.loaders.abstract import AbstractLoader
from parrot_loaders.splitters.semantic import SemanticTextSplitter
from parrot_loaders.splitters.token import TokenTextSplitter


class ConcreteTestLoader(AbstractLoader):
    """Minimal concrete implementation for testing."""

    async def _load(self, path, **kwargs):
        return []


class TestAbstractLoaderDefaults:
    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_default_chunk_size_2048(self, mock_device, mock_llm):
        """Default chunk_size is 2048."""
        loader = ConcreteTestLoader()
        assert loader.chunk_size == 2048

    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_default_chunk_overlap_200(self, mock_device, mock_llm):
        """Default chunk_overlap is 200."""
        loader = ConcreteTestLoader()
        assert loader.chunk_overlap == 200

    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_min_chunk_size_default_50(self, mock_device, mock_llm):
        """Default min_chunk_size is 50."""
        loader = ConcreteTestLoader()
        assert loader.min_chunk_size == 50

    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_full_document_default_true(self, mock_device, mock_llm):
        """Default full_document is True."""
        loader = ConcreteTestLoader()
        assert loader.full_document is True

    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_token_size_removed(self, mock_device, mock_llm):
        """token_size attribute no longer exists."""
        loader = ConcreteTestLoader()
        assert not hasattr(loader, 'token_size')

    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_semantic_splitter_is_default(self, mock_device, mock_llm):
        """Default text_splitter is SemanticTextSplitter."""
        loader = ConcreteTestLoader()
        assert isinstance(loader.text_splitter, SemanticTextSplitter)

    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_explicit_chunk_size_override(self, mock_device, mock_llm):
        """Passing chunk_size=800 explicitly still works."""
        loader = ConcreteTestLoader(chunk_size=800)
        assert loader.chunk_size == 800

    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_explicit_min_chunk_size_override(self, mock_device, mock_llm):
        """Passing min_chunk_size explicitly overrides the default."""
        loader = ConcreteTestLoader(min_chunk_size=100)
        assert loader.min_chunk_size == 100

    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_full_document_false_override(self, mock_device, mock_llm):
        """Passing full_document=False overrides the default."""
        loader = ConcreteTestLoader(full_document=False)
        assert loader.full_document is False

    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_select_splitter_code(self, mock_device, mock_llm):
        """_select_splitter_for_content returns TokenTextSplitter for code."""
        loader = ConcreteTestLoader()
        splitter = loader._select_splitter_for_content('code')
        assert isinstance(splitter, TokenTextSplitter)

    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_select_splitter_text(self, mock_device, mock_llm):
        """_select_splitter_for_content returns text_splitter for text."""
        loader = ConcreteTestLoader()
        splitter = loader._select_splitter_for_content('text')
        assert splitter is loader.text_splitter

    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_select_splitter_markdown(self, mock_device, mock_llm):
        """_select_splitter_for_content routes markdown to text_splitter."""
        loader = ConcreteTestLoader()
        splitter = loader._select_splitter_for_content('markdown')
        # Now markdown also routes to the semantic splitter
        assert splitter is loader.text_splitter

    @patch.object(AbstractLoader, '_setup_llm')
    @patch.object(AbstractLoader, '_setup_device')
    def test_explicit_text_splitter_overrides(self, mock_device, mock_llm):
        """Passing explicit text_splitter kwarg overrides the default."""
        custom_splitter = TokenTextSplitter(chunk_size=500)
        loader = ConcreteTestLoader(text_splitter=custom_splitter)
        assert loader.text_splitter is custom_splitter
