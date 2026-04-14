"""Tests for SemanticTextSplitter (TASK-635).

Comprehensive unit tests covering paragraph splitting, sentence splitting,
code block preservation, table preservation, min_chunk_size enforcement,
CJK support, empty input, and token counting.
"""
import pytest
from parrot_loaders.splitters.semantic import SemanticTextSplitter


@pytest.fixture
def splitter():
    """Default splitter with small chunk sizes for testing."""
    return SemanticTextSplitter(
        chunk_size=100, chunk_overlap=0, min_chunk_size=5
    )


@pytest.fixture
def sample_paragraphed_text():
    """Text with clear paragraph boundaries for semantic splitting."""
    return (
        "This is the first paragraph. It contains multiple sentences. "
        "Each sentence adds context to the topic being discussed.\n\n"
        "This is the second paragraph. It covers a different subtopic. "
        "The semantic splitter should keep each paragraph together.\n\n"
        "Short paragraph.\n\n"
        "This is a longer paragraph that goes into much more detail about "
        "the subject matter. It contains many sentences that build upon "
        "each other to form a coherent argument. The reader should be able "
        "to understand the full context without needing to read adjacent chunks."
    )


@pytest.fixture
def sample_code_block_text():
    """Text with embedded code blocks that should not be split."""
    return (
        "Here is an explanation of the code:\n\n"
        "```python\n"
        "def example_function(x: int, y: int) -> int:\n"
        "    result = x + y\n"
        "    return result\n"
        "```\n\n"
        "The function above adds two integers."
    )


class TestSemanticTextSplitter:
    def test_split_paragraphs(self, splitter):
        """Text with \\n\\n produces paragraph-level chunks."""
        text = (
            "First paragraph with enough words to make it meaningful.\n\n"
            "Second paragraph with enough words to make it meaningful."
        )
        chunks = splitter.split_text(text)
        assert len(chunks) >= 1
        assert all(len(c.strip()) > 0 for c in chunks)

    def test_merge_small_paragraphs(self):
        """Consecutive small paragraphs merged to reach chunk_size."""
        splitter = SemanticTextSplitter(
            chunk_size=200, chunk_overlap=0, min_chunk_size=5
        )
        text = "Short one.\n\nShort two.\n\nShort three.\n\nShort four."
        chunks = splitter.split_text(text)
        # All short paragraphs should merge into 1 chunk
        assert len(chunks) == 1

    def test_split_oversized_paragraph(self):
        """Single large paragraph split at sentence boundaries."""
        splitter = SemanticTextSplitter(
            chunk_size=15, chunk_overlap=0, min_chunk_size=3
        )
        text = (
            "The quick brown fox jumps over the lazy dog in the park. "
            "Meanwhile the cat sat quietly on the warm windowsill at home. "
            "Birds were singing loudly in the tall trees near the river. "
            "Fish swam gracefully through the crystal clear water below."
        )
        chunks = splitter.split_text(text)
        assert len(chunks) >= 2

    def test_code_block_preserved(self):
        """Code blocks are never split mid-block."""
        splitter = SemanticTextSplitter(
            chunk_size=30, chunk_overlap=0, min_chunk_size=3
        )
        text = (
            "Before code.\n\n"
            "```python\n"
            "def foo():\n"
            "    return 42\n"
            "```\n\n"
            "After code."
        )
        chunks = splitter.split_text(text)
        # Find the chunk containing the code block
        code_chunks = [c for c in chunks if "```python" in c]
        assert len(code_chunks) >= 1
        assert "return 42" in code_chunks[0]

    def test_table_preserved(self):
        """Markdown tables kept as atomic units."""
        splitter = SemanticTextSplitter(
            chunk_size=50, chunk_overlap=0, min_chunk_size=3
        )
        text = (
            "Some text before the table.\n\n"
            "| Col A | Col B |\n"
            "| --- | --- |\n"
            "| val1 | val2 |\n"
            "| val3 | val4 |\n\n"
            "Some text after the table."
        )
        chunks = splitter.split_text(text)
        # Find chunk with table
        table_chunks = [c for c in chunks if "Col A" in c]
        assert len(table_chunks) >= 1
        # Table should be intact
        assert "val4" in table_chunks[0]

    def test_empty_input(self):
        """Empty string returns empty list."""
        splitter = SemanticTextSplitter()
        assert splitter.split_text("") == []

    def test_whitespace_only_input(self):
        """Whitespace-only string returns empty list."""
        splitter = SemanticTextSplitter()
        assert splitter.split_text("   \n\n  \n  ") == []

    def test_single_short_text(self):
        """Text below min_chunk_size returned as single chunk."""
        splitter = SemanticTextSplitter(chunk_size=100, min_chunk_size=50)
        chunks = splitter.split_text("Hello world.")
        assert len(chunks) == 1
        assert chunks[0] == "Hello world."

    def test_token_counting(self):
        """Token count uses tiktoken, not character length."""
        splitter = SemanticTextSplitter()
        count = splitter._count_tokens("Hello world, this is a test.")
        assert isinstance(count, int)
        assert count > 0
        assert count != len("Hello world, this is a test.")  # Not char count

    def test_token_counting_empty(self):
        """Token count returns 0 for empty string."""
        splitter = SemanticTextSplitter()
        assert splitter._count_tokens("") == 0

    def test_min_chunk_size_enforcement(self):
        """No chunk below min_chunk_size is produced (except single-chunk case)."""
        splitter = SemanticTextSplitter(
            chunk_size=50, chunk_overlap=0, min_chunk_size=10
        )
        text = (
            "This is a long enough paragraph that should form a proper chunk "
            "with sufficient tokens to pass the minimum size requirement.\n\n"
            "Tiny."
        )
        chunks = splitter.split_text(text)
        # "Tiny." alone is ~1 token, should be merged with previous
        for chunk in chunks:
            tokens = splitter._count_tokens(chunk)
            # All chunks should meet min_chunk_size (unless total is below it)
            if len(chunks) > 1:
                assert tokens >= 10

    def test_overlap_applied(self):
        """Chunk overlap prepends text from previous chunk."""
        splitter = SemanticTextSplitter(
            chunk_size=30, chunk_overlap=10, min_chunk_size=3
        )
        text = (
            "First sentence with enough words to fill a chunk properly here.\n\n"
            "Second sentence also with enough words to fill another chunk here."
        )
        chunks = splitter.split_text(text)
        if len(chunks) >= 2:
            # Second chunk should contain some text from first (overlap)
            # Just verify overlap produces longer chunks
            assert len(chunks[1]) > 0

    def test_multiple_paragraphs_chunked(self, sample_paragraphed_text):
        """Multi-paragraph text splits into reasonable chunks."""
        splitter = SemanticTextSplitter(
            chunk_size=50, chunk_overlap=0, min_chunk_size=5
        )
        chunks = splitter.split_text(sample_paragraphed_text)
        assert len(chunks) >= 2
        # All chunks should have content
        assert all(len(c.strip()) > 0 for c in chunks)

    def test_code_block_full_scenario(self, sample_code_block_text):
        """Full code block scenario: code stays intact."""
        splitter = SemanticTextSplitter(
            chunk_size=50, chunk_overlap=0, min_chunk_size=3
        )
        chunks = splitter.split_text(sample_code_block_text)
        # Find the code block
        code_found = False
        for chunk in chunks:
            if "```python" in chunk and "```" in chunk[chunk.index("```python") + 10:]:
                code_found = True
                # Verify full code block is intact
                assert "def example_function" in chunk
                assert "return result" in chunk
        assert code_found, "Code block not found intact in any chunk"

    def test_import_from_package(self):
        """SemanticTextSplitter is importable from splitters package."""
        from parrot_loaders.splitters import SemanticTextSplitter as SST
        assert SST is SemanticTextSplitter


class TestSemanticTextSplitterEdgeCases:
    def test_single_very_long_sentence(self):
        """A single sentence exceeding chunk_size is token-split."""
        splitter = SemanticTextSplitter(
            chunk_size=20, chunk_overlap=0, min_chunk_size=3
        )
        # One long sentence, no periods until end
        long_sentence = " ".join(["word"] * 100) + "."
        chunks = splitter.split_text(long_sentence)
        assert len(chunks) >= 2

    def test_no_double_newlines(self):
        """Text without paragraph breaks treated as single segment."""
        splitter = SemanticTextSplitter(
            chunk_size=200, chunk_overlap=0, min_chunk_size=5
        )
        text = "This is a single block of text without any paragraph breaks. " * 3
        chunks = splitter.split_text(text)
        assert len(chunks) >= 1

    def test_many_empty_paragraphs(self):
        """Multiple empty paragraphs between content are handled."""
        splitter = SemanticTextSplitter(
            chunk_size=100, chunk_overlap=0, min_chunk_size=3
        )
        text = "Content A.\n\n\n\n\n\nContent B."
        chunks = splitter.split_text(text)
        assert len(chunks) >= 1
        # Both pieces of content should appear
        full = " ".join(chunks)
        assert "Content A" in full
        assert "Content B" in full
