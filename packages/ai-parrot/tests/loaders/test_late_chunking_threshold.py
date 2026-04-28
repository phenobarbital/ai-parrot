"""Tests for threshold routing in _chunk_with_late_chunking.

TASK-857 — 3-level hierarchy in late chunking.

Verifies that:
1. Documents above the threshold use the 3-level path (parent_chunks + children).
2. Documents at or below the threshold use the 2-level path (full_doc + children).
3. The 2-level path output is byte-equal regression-compatible with pre-FEAT-128.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict, List

import numpy as np
import pytest

from parrot.stores.models import Document
from parrot.stores.utils.chunking import LateChunkingProcessor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _long_text(chars: int) -> str:
    """Generate a text string of approximately `chars` characters."""
    word = "Lorem ipsum dolor sit amet. "
    return (word * (chars // len(word) + 1))[:chars]


def _make_mock_vector_store() -> MagicMock:
    store = MagicMock()
    store._embed_ = AsyncMock()
    store._embed_.embed_query = AsyncMock(return_value=[0.0] * 768)
    store._embed_.embed_documents = AsyncMock(return_value=[[0.0] * 768])
    return store


def _make_minimal_loader():
    """Create a minimal loader-like object that has _chunk_with_late_chunking."""
    # We test the method directly rather than through a full loader chain
    # to keep tests focused.  Use a simple namespace with the required attrs.
    class MinimalLoader:
        chunk_size = 512
        chunk_overlap = 50

        def __init__(self):
            import logging
            self.logger = logging.getLogger('test.loader')

        async def _chunk_with_text_splitter(self, documents):
            return documents

    from parrot.loaders.abstract import AbstractLoader
    # Borrow the method from AbstractLoader via unbound call
    loader = MinimalLoader()
    loader._chunk_with_late_chunking = AbstractLoader._chunk_with_late_chunking.__get__(
        loader, MinimalLoader
    )
    return loader


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLateChunkingThresholdRouting:
    @pytest.mark.asyncio
    async def test_small_doc_uses_2level_path(self):
        """A document below the threshold produces a full_doc parent + chunk children."""
        mock_store = _make_mock_vector_store()
        loader = _make_minimal_loader()

        # 500 chars < default 16000 threshold → 2-level path
        small = Document(
            page_content=_long_text(500),
            metadata={"document_id": "small-1"},
        )

        with patch(
            'parrot.loaders.abstract.LateChunkingProcessor',
            wraps=LateChunkingProcessor,
        ):
            out = await loader._chunk_with_late_chunking(
                [small],
                vector_store=mock_store,
                store_full_document=True,
            )

        parents = [d for d in out if d.metadata.get('is_full_document') is True]
        chunks = [d for d in out if d.metadata.get('is_chunk') is True]
        parent_chunks = [d for d in out if d.metadata.get('document_type') == 'parent_chunk']

        assert len(parents) == 1, "2-level path must produce exactly one full_doc parent"
        assert len(parent_chunks) == 0, "2-level path must NOT produce parent_chunk rows"
        assert len(chunks) >= 1, "2-level path must produce at least one child chunk"
        # Children must link to the original doc, not any UUID
        for chunk in chunks:
            assert chunk.metadata.get('parent_document_id') == 'small-1'

    @pytest.mark.asyncio
    async def test_large_doc_uses_3level_path(self):
        """A document above the threshold produces parent_chunks + children (no full_doc parent)."""
        mock_store = _make_mock_vector_store()
        loader = _make_minimal_loader()

        # 20000 chars > 16000 default threshold → 3-level path
        large = Document(
            page_content=_long_text(20000),
            metadata={"document_id": "large-1"},
        )

        out = await loader._chunk_with_late_chunking(
            [large],
            vector_store=mock_store,
            store_full_document=True,           # should be ignored on 3-level path
            parent_chunk_threshold_tokens=16000,
            parent_chunk_size_tokens=4000,
            parent_chunk_overlap_tokens=200,
        )

        full_docs = [d for d in out if d.metadata.get('is_full_document') is True]
        parent_chunks = [d for d in out if d.metadata.get('document_type') == 'parent_chunk']
        chunks = [d for d in out if d.metadata.get('is_chunk') is True]

        assert len(full_docs) == 0, "3-level path must NOT store the original doc as a parent"
        assert len(parent_chunks) >= 2, "3-level path must produce at least 2 parent_chunks"
        assert len(chunks) >= 1, "3-level path must produce child chunks"

        # Children must NOT link to the original doc ID
        parent_chunk_ids = {pc.metadata['document_id'] for pc in parent_chunks}
        for chunk in chunks:
            assert chunk.metadata.get('parent_document_id') in parent_chunk_ids, (
                f"Child links to {chunk.metadata.get('parent_document_id')!r} "
                f"which is not in parent_chunk IDs {parent_chunk_ids}"
            )

    @pytest.mark.asyncio
    async def test_2level_path_is_unchanged_for_docs_below_threshold(self):
        """The 2-level path behaviour is preserved for sub-threshold documents.

        Verifies byte-equal regression: same metadata keys, same parent marker.
        This is the regression test ensuring FEAT-128 did not break existing
        2-level ingestion.
        """
        mock_store = _make_mock_vector_store()
        loader = _make_minimal_loader()

        doc = Document(
            page_content=_long_text(1000),
            metadata={"document_id": "stable-id", "source": "handbook.pdf"},
        )

        out = await loader._chunk_with_late_chunking(
            [doc],
            vector_store=mock_store,
            store_full_document=True,
            parent_chunk_threshold_tokens=16000,
        )

        # The full_doc parent must have the same structure as before FEAT-128
        full_docs = [d for d in out if d.metadata.get('is_full_document') is True]
        assert len(full_docs) == 1
        parent = full_docs[0]
        assert parent.metadata['document_id'] == 'stable-id'
        assert parent.metadata['document_type'] == 'parent'
        assert parent.metadata['chunking_strategy'] == 'late_chunking'
        assert parent.page_content == doc.page_content  # original text preserved

    @pytest.mark.asyncio
    async def test_custom_threshold_respected(self):
        """A custom threshold routes correctly."""
        mock_store = _make_mock_vector_store()
        loader = _make_minimal_loader()

        # 1500-char doc with threshold=1000 → should use 3-level path
        doc = Document(
            page_content=_long_text(1500),
            metadata={"document_id": "threshold-test"},
        )

        out = await loader._chunk_with_late_chunking(
            [doc],
            vector_store=mock_store,
            store_full_document=True,
            parent_chunk_threshold_tokens=1000,  # custom low threshold
            parent_chunk_size_tokens=400,
            parent_chunk_overlap_tokens=50,
        )

        parent_chunks = [d for d in out if d.metadata.get('document_type') == 'parent_chunk']
        full_docs = [d for d in out if d.metadata.get('is_full_document') is True]

        assert len(parent_chunks) >= 1
        assert len(full_docs) == 0

    @pytest.mark.asyncio
    async def test_new_kwargs_have_correct_defaults(self):
        """_chunk_with_late_chunking has the correct default values for new kwargs."""
        import inspect
        from parrot.loaders.abstract import AbstractLoader

        sig = inspect.signature(AbstractLoader._chunk_with_late_chunking)
        params = sig.parameters

        assert 'parent_chunk_threshold_tokens' in params
        assert params['parent_chunk_threshold_tokens'].default == 16000

        assert 'parent_chunk_size_tokens' in params
        assert params['parent_chunk_size_tokens'].default == 4000

        assert 'parent_chunk_overlap_tokens' in params
        assert params['parent_chunk_overlap_tokens'].default == 200
