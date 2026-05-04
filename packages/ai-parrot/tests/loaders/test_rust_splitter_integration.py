"""Integration test: confirm the Rust-backed splitters are wired into
AbstractLoader and actually fix the mid-word-cut bug end-to-end.
"""
import pytest

from parrot_loaders.splitters import (
    SemanticTextSplitter,
    MarkdownTextSplitter,
)


def _no_mid_word(chunk: str, full_text: str) -> bool:
    """A chunk respects word boundaries when its first and last
    characters are either at the start/end of the source text or are
    bordered by whitespace in the source.
    """
    start = full_text.find(chunk)
    if start == -1:
        return False
    end = start + len(chunk)
    starts_clean = start == 0 or full_text[start - 1].isspace()
    ends_clean = (
        end == len(full_text)
        or full_text[end].isspace()
        or chunk[-1] in ".!?,;:"
    )
    return starts_clean and ends_clean


@pytest.fixture
def minimal_loader():
    """Minimal concrete AbstractLoader subclass for testing splitter wiring."""
    from parrot.loaders.abstract import AbstractLoader

    class _MinimalLoader(AbstractLoader):
        async def _load(self, source, *args, **kwargs):
            return []

    return _MinimalLoader(
        chunk_size=512,
        chunk_overlap=50,
        min_chunk_size=30,
    )


def test_splitter_classes_resolve_via_consumer_path():
    """The class names imported by abstract.py still resolve to our wrappers."""
    from parrot.loaders import abstract as abstract_mod
    assert abstract_mod.SemanticTextSplitter is SemanticTextSplitter
    assert abstract_mod.MarkdownTextSplitter is MarkdownTextSplitter


def test_default_text_splitter_is_rust_backed(minimal_loader):
    """AbstractLoader._setup_text_splitters builds the new Rust-backed wrapper."""
    assert minimal_loader.text_splitter.__class__.__name__ == "SemanticTextSplitter"
    # Confirm the Rust splitter is wired underneath
    assert hasattr(minimal_loader.text_splitter, "_rust"), (
        "SemanticTextSplitter must expose _rust attribute"
    )
    assert minimal_loader.text_splitter._rust.__class__.__name__ == "TextSplitter"


def test_no_mid_word_cuts_for_long_non_atomic_doc(minimal_loader):
    """FEAT-141 regression: long-form content must not be chunked mid-word.

    Uses the AT&T AutoPay text that triggered the original production bug.
    """
    text = (
        "Your AT&T Prepaid account allows you to see your data "
        "usage, change your plan, check your balance, enroll & "
        "set up AutoPay. "
    ) * 30
    chunks = minimal_loader.text_splitter.split_text(text)
    assert chunks, "splitter returned no chunks"
    for c in chunks:
        assert _no_mid_word(c, text), f"mid-word cut detected: {c!r}"
    # AutoPay must appear intact in at least one chunk
    assert any("set up AutoPay" in c for c in chunks), (
        "AutoPay regression: 'set up AutoPay' was split mid-phrase"
    )
