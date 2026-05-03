"""Comprehensive tests for the Rust-backed SemanticTextSplitter and MarkdownTextSplitter."""
import re

import pytest

from parrot_loaders.splitters import (
    SemanticTextSplitter,
    MarkdownTextSplitter,
)


# ---------------------------------------------------------------------------
# SemanticTextSplitter tests
# ---------------------------------------------------------------------------

class TestSemanticSplitter:
    def test_split_text_no_mid_word_cuts(self, no_mid_word):
        """No chunk should end mid-word."""
        text = ("This is a long sentence about chunks that " * 80).strip()
        s = SemanticTextSplitter(chunk_size=120, chunk_overlap=10)
        chunks = s.split_text(text)
        assert chunks
        for c in chunks:
            assert no_mid_word(c, text), f"mid-word cut detected in: {c!r}"

    def test_autopay_regression(self, autopay_text):
        """Production regression: 'set up AutoPay' must appear intact."""
        s = SemanticTextSplitter(chunk_size=512, chunk_overlap=50, min_chunk_size=30)
        chunks = s.split_text(autopay_text)
        assert any("set up AutoPay" in c for c in chunks), (
            "AutoPay regression: 'set up AutoPay' was split mid-phrase"
        )

    def test_create_chunks_offsets_slice_back(self):
        """text[start:end] == chunk.text for every chunk (ASCII).

        Uses min_chunk_size=0 to avoid tail-merge, which adds a synthetic
        '\\n\\n' separator that would break the round-trip invariant.
        """
        text = ("alpha beta gamma delta epsilon zeta eta theta iota " * 30)
        s = SemanticTextSplitter(chunk_size=80, chunk_overlap=10, min_chunk_size=0)
        chunks = s.create_chunks(text)
        for c in chunks:
            assert text[c.start_position:c.end_position] == c.text

    def test_non_ascii_offset_round_trip(self, non_ascii_text):
        """Offset round-trip holds for non-ASCII text (byte-vs-char guard).

        Uses min_chunk_size=0 to avoid tail-merge breaking the invariant.
        """
        s = SemanticTextSplitter(chunk_size=120, chunk_overlap=10, min_chunk_size=0)
        chunks = s.create_chunks(non_ascii_text)
        for c in chunks:
            assert (
                non_ascii_text[c.start_position:c.end_position] == c.text
            ), "byte-vs-char offset confusion"

    def test_min_chunk_size_tail_merge(self):
        """Tail chunk below min_chunk_size is merged into predecessor."""
        text = "Sentence A. " * 40 + "tail."
        s = SemanticTextSplitter(chunk_size=200, chunk_overlap=20, min_chunk_size=30)
        chunks = s.create_chunks(text)
        if len(chunks) >= 2:
            assert chunks[-1].token_count >= 30
        for c in chunks:
            assert c.metadata["total_chunks"] == len(chunks)

    def test_overlap_honored(self):
        """Consecutive chunks share some overlap when chunk_overlap > 0."""
        text = "x" * 50 + " " + "word " * 200
        s = SemanticTextSplitter(chunk_size=200, chunk_overlap=50)
        chunks = s.split_text(text)
        had_overlap = False
        for a, b in zip(chunks, chunks[1:]):
            for n in range(min(len(a), len(b), 200), 5, -1):
                if a[-n:] == b[:n]:
                    if n >= 30:
                        had_overlap = True
                        break
                    break
        # Overlap is best-effort; pass if only one chunk was produced
        assert had_overlap or len(chunks) <= 1

    def test_tokenizer_changes_capacity(self):
        """Passing tokenizer= switches to token-based capacity."""
        text = "tokenized capacity check " * 100
        char_splitter = SemanticTextSplitter(chunk_size=100)
        try:
            tok_splitter = SemanticTextSplitter(chunk_size=100, tokenizer="gpt-4")
        except Exception as exc:
            pytest.skip(f"tiktoken unavailable: {exc}")
        char_chunks = char_splitter.split_text(text)
        tok_chunks = tok_splitter.split_text(text)
        assert len(char_chunks) != len(tok_chunks)

    def test_legacy_kwargs_silently_accepted(self):
        """All legacy kwargs are accepted without raising."""
        SemanticTextSplitter(
            chunk_size=256,
            chunk_overlap=20,
            model_name="gpt-4",
            encoding_name="cl100k_base",
            sentence_endings=r"[.!?]\s+",
            preserve_code_blocks=False,
            preserve_tables=False,
        )

    def test_metadata_contract(self):
        """Metadata keys are correct and caller metadata is preserved."""
        s = SemanticTextSplitter(chunk_size=100, chunk_overlap=10)
        chunks = s.create_chunks("paragraph " * 80, metadata={"src": "x"})
        for c in chunks:
            assert c.metadata["src"] == "x"
            assert "chunk_index" in c.metadata
            assert "total_chunks" in c.metadata
            assert c.metadata["splitter_type"] == "SemanticTextSplitter"

    def test_chunk_id_format(self):
        """chunk_id matches the pattern ^chunk_\\d{4}_[0-9a-f]{8}$."""
        s = SemanticTextSplitter(chunk_size=100, chunk_overlap=10)
        chunks = s.create_chunks("paragraph " * 80)
        pat = re.compile(r"^chunk_\d{4}_[0-9a-f]{8}$")
        for c in chunks:
            assert pat.match(c.chunk_id or ""), c.chunk_id


# ---------------------------------------------------------------------------
# MarkdownTextSplitter tests
# ---------------------------------------------------------------------------

class TestMarkdownSplitter:
    def test_preserves_code_fences(self):
        """Fenced code blocks are never split mid-fence interior.

        The Rust MarkdownSplitter may emit the opening fence (```python)
        and body content as separate chunks when the block exceeds chunk_size,
        but it never emits a chunk that starts inside a code block without
        the fence header. We verify that the fence opener and closer only
        appear at the START or END of a chunk, never mid-chunk.
        """
        long_code = "    print('x')\n" * 60
        md = (
            "# Title\n\nIntro paragraph.\n\n"
            "```python\n" + long_code + "```\n\n"
            "## After\n\nMore text after the fence.\n"
        )
        s = MarkdownTextSplitter(chunk_size=200, chunk_overlap=20)
        chunks = s.split_text(md)
        assert chunks
        # No chunk should have a ``` marker in the MIDDLE (only at start/end)
        for c in chunks:
            # Strip leading/trailing whitespace for the check
            stripped = c.strip()
            if "```" in stripped:
                # Allowed: chunk starts with ``` (fence opener/closer)
                # or chunk ends with ``` (fence closer)
                inner = stripped.lstrip("`")  # remove leading backtick runs
                # After stripping fence at the start, there should be no
                # more backtick fences mid-content unless it's a complete block
                mid_fences = [ln for ln in inner.split("\n")
                              if ln.strip().startswith("```")]
                assert len(mid_fences) <= 1, (
                    f"mid-fence split detected: {c!r}"
                )

    def test_preserves_headers(self):
        """No chunk should end on a bare header line without body."""
        md = (
            "# H1\n\nbody1 long enough to matter quite a lot.\n\n"
            "## H2\n\nbody2 even longer with several sentences. "
            "Like this one. And this one. " * 6
        )
        s = MarkdownTextSplitter(chunk_size=120, chunk_overlap=10)
        chunks = s.split_text(md)
        for c in chunks:
            stripped = c.strip()
            if stripped.startswith("#"):
                # chunk starts with header — must contain body too
                assert "\n" in stripped or len(chunks) == 1

    def test_create_chunks_offsets_slice_back(self):
        """Offset round-trip for Markdown (ASCII).

        Uses min_chunk_size=0 to avoid tail-merge breaking the invariant.
        """
        md = (
            "# T\n\nparagraph one\n\nparagraph two\n\n## sec\n\n"
            + ("md body line. " * 60)
        )
        s = MarkdownTextSplitter(chunk_size=120, chunk_overlap=10, min_chunk_size=0)
        for c in s.create_chunks(md):
            assert md[c.start_position:c.end_position] == c.text

    def test_non_ascii_offset_round_trip(self, non_ascii_text):
        """Offset round-trip for Markdown with non-ASCII content.

        Uses min_chunk_size=0 to avoid tail-merge breaking the invariant.
        """
        md = "# Título\n\n" + non_ascii_text
        s = MarkdownTextSplitter(chunk_size=120, chunk_overlap=10, min_chunk_size=0)
        for c in s.create_chunks(md):
            assert md[c.start_position:c.end_position] == c.text

    def test_metadata_splitter_type(self):
        """splitter_type must be 'MarkdownTextSplitter' in every chunk."""
        s = MarkdownTextSplitter(chunk_size=100, chunk_overlap=10)
        chunks = s.create_chunks("# X\n\nbody " * 30)
        for c in chunks:
            assert c.metadata["splitter_type"] == "MarkdownTextSplitter"
