"""Unit tests for SpeakableFlattener (TASK-005)."""
from __future__ import annotations

import pytest

from parrot.integrations.liveavatar import SpeakableFlattener


# ---------------------------------------------------------------------------
# Markdown stripping
# ---------------------------------------------------------------------------

def test_flattener_strips_code_fence() -> None:
    """Code fences and their content are removed."""
    f = SpeakableFlattener()
    out = f.feed("Here is code:\n```python\nprint(1)\n```\nDone.") + f.flush()
    text = " ".join(out)
    assert "print(1)" not in text, "Code content must be stripped"
    assert "```" not in text, "Code fence markers must be stripped"
    assert "Done" in text, "Text after code fence must survive"


def test_flattener_strips_inline_code() -> None:
    """Inline code backtick markers and content are removed."""
    f = SpeakableFlattener()
    out = f.feed("Use `os.path.join()` to join paths.") + f.flush()
    text = " ".join(out)
    assert "os.path.join()" not in text
    assert "`" not in text


def test_flattener_strips_table() -> None:
    """Markdown tables are removed."""
    f = SpeakableFlattener()
    table = "| Column A | Column B |\n|----------|----------|\n| Cell 1   | Cell 2   |"
    out = f.feed(table + "\nAfter table.") + f.flush()
    text = " ".join(out)
    assert "Column A" not in text
    assert "Cell 1" not in text
    assert "After table" in text


def test_flattener_strips_heading_markers() -> None:
    """Heading markers are stripped but the heading text survives."""
    f = SpeakableFlattener()
    out = f.feed("## Introduction\nSome text.") + f.flush()
    text = " ".join(out)
    assert "##" not in text
    assert "Introduction" in text
    assert "Some text" in text


def test_flattener_strips_bold_italic() -> None:
    """Bold (**) and italic (*) markers are stripped; text survives."""
    f = SpeakableFlattener()
    out = f.feed("This is **bold** and *italic* text.") + f.flush()
    text = " ".join(out)
    assert "**" not in text
    assert "*" not in text
    assert "bold" in text
    assert "italic" in text


def test_flattener_preserves_link_text() -> None:
    """Links keep their display text; URLs are dropped."""
    f = SpeakableFlattener()
    out = f.feed("See [the docs](https://example.com) for more.") + f.flush()
    text = " ".join(out)
    assert "the docs" in text
    assert "https://example.com" not in text
    assert "[" not in text


def test_flattener_strips_list_bullets() -> None:
    """List bullet markers are removed."""
    f = SpeakableFlattener()
    out = f.feed("Items:\n- First\n- Second\n- Third") + f.flush()
    text = " ".join(out)
    assert "First" in text and "Second" in text and "Third" in text
    assert "- " not in text


# ---------------------------------------------------------------------------
# Sentence segmentation
# ---------------------------------------------------------------------------

def test_sentence_segmenter_incremental() -> None:
    """A sentence split across two feed() calls is emitted once, complete."""
    f = SpeakableFlattener()
    s1 = f.feed("Hello wor")
    s2 = f.feed("ld. How are you?")
    # First feed should return nothing (no complete sentence yet)
    assert s1 == [], f"Expected empty from first feed, got {s1}"
    # Second feed should emit at least one complete sentence
    combined = " ".join(s2)
    assert "Hello world" in combined, f"'Hello world' expected in {s2}"
    assert "How are you?" in combined or any("How are you?" in s for s in s2)


def test_sentence_segmenter_multiple_sentences() -> None:
    """Multiple sentences in one feed() call are all emitted."""
    f = SpeakableFlattener()
    out = f.feed("First sentence. Second sentence! Third sentence?")
    text = " ".join(out)
    assert "First sentence" in text
    assert "Second sentence" in text


def test_flush_returns_trailing_text() -> None:
    """flush() returns trailing text without terminal punctuation."""
    f = SpeakableFlattener()
    f.feed("This is incomplete")  # no sentence boundary
    rest = f.flush()
    assert rest, "flush() should return remaining content"
    assert "incomplete" in " ".join(rest)


def test_flush_empty_on_empty_buffer() -> None:
    """flush() on an empty buffer returns []."""
    f = SpeakableFlattener()
    assert f.flush() == []


def test_feed_empty_string() -> None:
    """feed('') does not emit anything."""
    f = SpeakableFlattener()
    assert f.feed("") == []


def test_multi_feed_accumulates() -> None:
    """Buffer grows across feed() calls until a sentence boundary is found."""
    f = SpeakableFlattener()
    assert f.feed("One") == []
    assert f.feed(" two") == []
    assert f.feed(" three") == []
    result = f.feed(" four.")
    text = " ".join(result + f.flush())
    assert "four" in text


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_flattener_unclosed_code_fence_no_crash() -> None:
    """Unclosed code fence does not raise."""
    f = SpeakableFlattener()
    # Should not raise; partial fence handled gracefully
    out = f.feed("Text before\n```python\nprint(") + f.flush()
    assert isinstance(out, list)


def test_flattener_plain_text_passthrough() -> None:
    """Plain text with no markdown passes through unchanged (modulo whitespace)."""
    f = SpeakableFlattener()
    text = "Hello world. This is a test."
    out = f.feed(text) + f.flush()
    combined = " ".join(out)
    assert "Hello world" in combined
    assert "This is a test" in combined
