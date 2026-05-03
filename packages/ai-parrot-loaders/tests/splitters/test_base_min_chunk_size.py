"""Tests for BaseTextSplitter._enforce_min_chunk_size and the
legacy create_chunks path (must remain byte-identical post-refactor)."""

import pytest
from parrot_loaders.splitters.base import BaseTextSplitter, TextChunk


class _DummySplitter(BaseTextSplitter):
    """Minimal concrete subclass for exercising the base behavior."""

    def split_text(self, text: str):
        # split into fixed-size pieces by whitespace tokens
        words = text.split()
        size = max(1, self.chunk_size)
        return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


@pytest.fixture
def splitter_min30() -> _DummySplitter:
    return _DummySplitter(chunk_size=10, min_chunk_size=30)


def _serialize(chunks):
    return [
        {
            "text": c.text,
            "start_position": c.start_position,
            "end_position": c.end_position,
            "token_count": c.token_count,
            "metadata": dict(c.metadata),
        }
        for c in chunks
    ]


class TestEnforceMinChunkSize:
    def test_noop_when_min_zero(self):
        s = _DummySplitter(chunk_size=10, min_chunk_size=0)
        chunks = s.create_chunks("a " * 50)
        again = s._enforce_min_chunk_size(list(chunks))
        assert _serialize(again) == _serialize(chunks)

    def test_noop_when_single_chunk(self, splitter_min30):
        chunks = splitter_min30.create_chunks("hello world")
        assert len(chunks) <= 1
        again = splitter_min30._enforce_min_chunk_size(list(chunks))
        assert _serialize(again) == _serialize(chunks)

    def test_idempotent(self, splitter_min30):
        chunks = splitter_min30.create_chunks("a " * 50)
        once = splitter_min30._enforce_min_chunk_size(list(chunks))
        twice = splitter_min30._enforce_min_chunk_size(list(once))
        assert _serialize(once) == _serialize(twice)

    def test_total_chunks_updated_after_merge(self):
        # Construct a scenario where the tail is undersized
        s = _DummySplitter(chunk_size=2, min_chunk_size=5)
        text = "alpha beta gamma delta epsilon"
        chunks = s.create_chunks(text)
        # All surviving chunks should agree on total_chunks
        totals = {c.metadata["total_chunks"] for c in chunks}
        assert len(totals) == 1
        assert totals.pop() == len(chunks)

    def test_legacy_path_preserves_metadata_keys(self, splitter_min30):
        chunks = splitter_min30.create_chunks(
            "a " * 80, metadata={"src": "fixture"}
        )
        for c in chunks:
            assert "chunk_index" in c.metadata
            assert "total_chunks" in c.metadata
            assert c.metadata["splitter_type"] == "_DummySplitter"
            assert c.metadata["src"] == "fixture"

    def test_noop_when_all_chunks_satisfy_minimum(self):
        # All chunks already meet the minimum — no merge should happen
        s = _DummySplitter(chunk_size=10, min_chunk_size=1)
        text = "a " * 100
        chunks = s.create_chunks(text)
        original_count = len(chunks)
        again = s._enforce_min_chunk_size(list(chunks))
        assert len(again) == original_count
