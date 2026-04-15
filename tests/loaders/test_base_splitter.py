"""Tests for BaseTextSplitter enhancements (TASK-633).

Verifies:
- min_chunk_size parameter acceptance and defaults
- Default _count_tokens() word-based estimate
- create_chunks() merges undersized final chunks
"""
import pytest
from parrot_loaders.splitters.base import BaseTextSplitter, TextChunk


class ConcreteTestSplitter(BaseTextSplitter):
    """Concrete splitter for testing (splits on double newline)."""

    def split_text(self, text: str):
        return [p.strip() for p in text.split('\n\n') if p.strip()]


class TestBaseTextSplitterEnhancements:
    def test_min_chunk_size_parameter(self):
        """min_chunk_size parameter accepted and stored."""
        splitter = ConcreteTestSplitter(chunk_size=100, min_chunk_size=10)
        assert splitter.min_chunk_size == 10

    def test_min_chunk_size_default_zero(self):
        """Default min_chunk_size is 0 (no enforcement)."""
        splitter = ConcreteTestSplitter()
        assert splitter.min_chunk_size == 0

    def test_default_count_tokens(self):
        """Default _count_tokens uses word-based estimate."""
        splitter = ConcreteTestSplitter()
        count = splitter._count_tokens("hello world foo bar")
        assert count > 0  # should be ~5 (4 words * 1.3)
        assert count == int(4 * 1.3)

    def test_count_tokens_empty_string(self):
        """_count_tokens returns 0 for empty string."""
        splitter = ConcreteTestSplitter()
        assert splitter._count_tokens("") == 0

    def test_merge_undersized_final_chunk(self):
        """Final chunk below min_chunk_size is merged with previous."""
        splitter = ConcreteTestSplitter(chunk_size=5000, min_chunk_size=10)
        text = (
            "This is a long paragraph with enough words to pass the minimum "
            "chunk size threshold easily and clearly.\n\nTiny."
        )
        chunks = splitter.create_chunks(text)
        # "Tiny." alone has ~1 token, should be merged with previous
        assert len(chunks) == 1
        assert "Tiny." in chunks[0].text

    def test_no_merge_when_min_chunk_size_zero(self):
        """No merging when min_chunk_size is 0."""
        splitter = ConcreteTestSplitter(chunk_size=5000, min_chunk_size=0)
        text = "First paragraph.\n\nSecond paragraph."
        chunks = splitter.create_chunks(text)
        assert len(chunks) == 2

    def test_no_merge_when_last_chunk_meets_min(self):
        """No merging when last chunk meets min_chunk_size."""
        splitter = ConcreteTestSplitter(chunk_size=5000, min_chunk_size=2)
        text = (
            "First paragraph with enough words here.\n\n"
            "Second paragraph also with enough words here."
        )
        chunks = splitter.create_chunks(text)
        assert len(chunks) == 2

    def test_single_chunk_no_merge(self):
        """Single chunk doesn't trigger merge logic."""
        splitter = ConcreteTestSplitter(chunk_size=5000, min_chunk_size=10)
        text = "Just one paragraph."
        chunks = splitter.create_chunks(text)
        assert len(chunks) == 1

    def test_existing_subclass_still_works(self):
        """Existing splitters that override _count_tokens still work."""
        class CustomSplitter(BaseTextSplitter):
            def split_text(self, text):
                return [text]

            def _count_tokens(self, text):
                return len(text)  # Character-based counting

        splitter = CustomSplitter(chunk_size=100)
        count = splitter._count_tokens("hello")
        assert count == 5  # Custom implementation wins

    def test_kwargs_passed_through(self):
        """Extra kwargs don't break initialization."""
        splitter = ConcreteTestSplitter(
            chunk_size=100,
            min_chunk_size=10,
            some_extra_kwarg="test"
        )
        assert splitter.min_chunk_size == 10
        assert splitter.chunk_size == 100
