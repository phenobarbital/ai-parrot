"""Unit tests for LateChunkingProcessor.process_document_three_level.

TASK-857 — 3-level hierarchy in late chunking.

These tests use a mocked vector store to avoid real embedding calls.
"""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from parrot.stores.models import Document
from parrot.stores.utils.chunking import ChunkInfo, LateChunkingProcessor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_vector_store() -> MagicMock:
    """Build a mock vector store that returns zero embeddings."""
    store = MagicMock()
    # _embed_ is the embedding model attribute used by LateChunkingProcessor
    store._embed_ = AsyncMock()
    store._embed_.embed_query = AsyncMock(return_value=[0.0] * 768)
    return store


def _make_processor(chunk_size: int = 512) -> LateChunkingProcessor:
    return LateChunkingProcessor(
        vector_store=_make_mock_vector_store(),
        chunk_size=chunk_size,
        chunk_overlap=50,
        min_chunk_size=10,
    )


def _long_text(chars: int) -> str:
    """Generate a text string of approximately `chars` characters."""
    word = "Lorem ipsum dolor sit amet. "
    return (word * (chars // len(word) + 1))[:chars]


# ---------------------------------------------------------------------------
# Tests for process_document_three_level
# ---------------------------------------------------------------------------


class TestThreeLevelChunking:
    @pytest.mark.asyncio
    async def test_split_into_multiple_parent_chunks(self):
        """A document larger than the parent_chunk_size is split into multiple parent_chunks."""
        processor = _make_processor()
        # Create text larger than 3 parent chunks of 1000 chars each
        long_text = _long_text(5000)

        parents, children = await processor.process_document_three_level(
            document_text=long_text,
            document_id='doc-large-1',
            metadata={'title': 'Long'},
            parent_chunk_size_tokens=1000,
            parent_chunk_overlap_tokens=50,
        )

        assert len(parents) >= 2, "Expected at least 2 parent_chunks for 5000-char doc"
        for p in parents:
            assert p.metadata['document_type'] == 'parent_chunk'
            assert p.metadata['is_chunk'] is False
            assert p.metadata['source_document_id'] == 'doc-large-1'
            assert 'document_id' in p.metadata

    @pytest.mark.asyncio
    async def test_children_link_to_parent_chunks_not_original_doc(self):
        """Each child's parent_document_id points to a parent_chunk's UUID, not the original doc."""
        processor = _make_processor()
        long_text = _long_text(3000)

        parents, children = await processor.process_document_three_level(
            document_text=long_text,
            document_id='doc-original',
            metadata={},
            parent_chunk_size_tokens=1000,
            parent_chunk_overlap_tokens=50,
        )

        parent_ids = {p.metadata['document_id'] for p in parents}
        for child in children:
            assert child.parent_document_id in parent_ids, (
                f"Child parent_document_id {child.parent_document_id!r} "
                f"not in parent_chunk IDs {parent_ids}"
            )
            assert child.parent_document_id != 'doc-original', (
                "Child should NOT link to the original doc ID"
            )

    @pytest.mark.asyncio
    async def test_parent_chunk_metadata_shape(self):
        """Parent_chunk documents have the required metadata fields."""
        processor = _make_processor()
        long_text = _long_text(2500)

        parents, _ = await processor.process_document_three_level(
            document_text=long_text,
            document_id='doc-meta-test',
            metadata={'collection': 'test'},
            parent_chunk_size_tokens=1000,
            parent_chunk_overlap_tokens=50,
        )

        assert len(parents) >= 1
        for i, p in enumerate(parents):
            assert p.metadata['document_type'] == 'parent_chunk'
            assert p.metadata['is_chunk'] is False
            assert p.metadata['source_document_id'] == 'doc-meta-test'
            assert p.metadata['parent_chunk_index'] == i
            # Must have a unique document_id (UUID)
            assert len(p.metadata['document_id']) > 0

    @pytest.mark.asyncio
    async def test_overlap_validation_raises_value_error(self):
        """ValueError is raised when overlap >= parent_chunk_size."""
        processor = _make_processor()

        with pytest.raises(ValueError, match="overlap"):
            await processor.process_document_three_level(
                document_text="x" * 100,
                document_id='doc-1',
                metadata={},
                parent_chunk_size_tokens=200,
                parent_chunk_overlap_tokens=300,
            )

    @pytest.mark.asyncio
    async def test_equal_overlap_and_size_raises_value_error(self):
        """ValueError is raised when overlap == parent_chunk_size."""
        processor = _make_processor()

        with pytest.raises(ValueError):
            await processor.process_document_three_level(
                document_text="x" * 100,
                document_id='doc-1',
                metadata={},
                parent_chunk_size_tokens=100,
                parent_chunk_overlap_tokens=100,
            )

    @pytest.mark.asyncio
    async def test_children_have_is_chunk_true(self):
        """All children produced by the 3-level path have is_chunk=True."""
        processor = _make_processor()
        long_text = _long_text(2500)

        _, children = await processor.process_document_three_level(
            document_text=long_text,
            document_id='doc-chunks',
            metadata={},
            parent_chunk_size_tokens=1000,
            parent_chunk_overlap_tokens=50,
        )

        assert len(children) > 0
        for child in children:
            assert child.metadata.get('is_chunk') is True

    @pytest.mark.asyncio
    async def test_source_document_id_preserved_on_children(self):
        """Children inherit source_document_id via their parent_chunk's metadata."""
        processor = _make_processor()
        long_text = _long_text(2500)

        _, children = await processor.process_document_three_level(
            document_text=long_text,
            document_id='doc-source-test',
            metadata={},
            parent_chunk_size_tokens=1000,
            parent_chunk_overlap_tokens=50,
        )

        for child in children:
            assert child.metadata.get('source_document_id') == 'doc-source-test'

    @pytest.mark.asyncio
    async def test_small_doc_with_large_parent_chunk_size(self):
        """A doc smaller than parent_chunk_size still produces at least one parent_chunk."""
        processor = _make_processor()
        short_text = _long_text(500)

        parents, children = await processor.process_document_three_level(
            document_text=short_text,
            document_id='doc-small',
            metadata={},
            parent_chunk_size_tokens=2000,   # larger than the doc
            parent_chunk_overlap_tokens=50,
        )

        assert len(parents) >= 1
        # All children should link to one of the parent_chunks
        parent_ids = {p.metadata['document_id'] for p in parents}
        for child in children:
            assert child.parent_document_id in parent_ids
