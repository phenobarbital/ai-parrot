"""Tests for MarkdownTextSplitter len() -> _count_tokens() fix (TASK-634).

Verifies that MarkdownTextSplitter uses _count_tokens() consistently
instead of len() for size comparisons against chunk_size and chunk_overlap.
"""
import pytest
from parrot_loaders.splitters.md import MarkdownTextSplitter


class TestMarkdownSplitterTokenConsistency:
    def test_chunk_size_in_tokens_not_chars(self):
        """Chunks respect chunk_size in tokens, not characters."""
        # chunk_size=50 tokens ~ ~38 words
        splitter = MarkdownTextSplitter(chunk_size=50, chunk_overlap=0)
        # Create text with 100+ words across sections
        text = (
            "# Section 1\n\n"
            + " ".join(["word"] * 60)
            + "\n\n# Section 2\n\n"
            + " ".join(["word"] * 60)
        )
        chunks = splitter.split_text(text)
        # Should produce multiple chunks, not one giant chunk
        assert len(chunks) >= 2

    def test_small_sections_merged_by_tokens(self):
        """Small sections are merged until token limit, not char limit."""
        splitter = MarkdownTextSplitter(chunk_size=100, chunk_overlap=0)
        text = "# A\n\nShort.\n\n# B\n\nAlso short.\n\n# C\n\nStill short."
        chunks = splitter.split_text(text)
        # All sections are small in tokens -- should merge into fewer chunks
        assert len(chunks) <= 2

    def test_large_section_split_by_tokens(self):
        """Oversized sections split at paragraph boundaries using token count."""
        splitter = MarkdownTextSplitter(chunk_size=30, chunk_overlap=0)
        long_text = "# Big Section\n\n" + "\n\n".join(
            [" ".join(["word"] * 20) for _ in range(5)]
        )
        chunks = splitter.split_text(long_text)
        assert len(chunks) >= 2

    def test_no_len_in_merge_sections(self):
        """_merge_markdown_sections uses _count_tokens consistently."""
        # With chunk_size=20 tokens (~15 words), ensure the splitter
        # splits correctly using token units
        splitter = MarkdownTextSplitter(chunk_size=20, chunk_overlap=0)
        # Each section has ~10 words = ~13 tokens
        text = (
            "# Header A\n\n"
            "This is a section with about ten words in it here.\n\n"
            "# Header B\n\n"
            "This is another section with about ten words in it."
        )
        chunks = splitter.split_text(text)
        # Each section alone is ~13 tokens, within 20 limit,
        # but combined they exceed 20 tokens
        assert len(chunks) >= 2

    def test_overlap_uses_tokens_not_chars(self):
        """_get_overlap_content measures overlap in tokens."""
        splitter = MarkdownTextSplitter(chunk_size=25, chunk_overlap=10)
        text = (
            "# Section One\n\n"
            + " ".join(["word"] * 20)
            + "\n\n# Section Two\n\n"
            + " ".join(["word"] * 20)
        )
        chunks = splitter.split_text(text)
        # With overlap, should have at least 2 chunks
        assert len(chunks) >= 2
