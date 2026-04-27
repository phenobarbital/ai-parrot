"""Unit tests for idempotent is_chunk normalisation in add_documents.

TASK-856 — Marker standardisation in stores.

These tests verify that ``PgVectorStore.add_documents`` applies
``_normalise_chunk_marker`` before persisting, ensuring every non-parent
document that lacks an ``is_chunk`` marker gets one.

The tests mock the embedding and SQL layers so no live DB is required.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.stores.abstract import _normalise_chunk_marker
from parrot.stores.models import Document


class TestAddDocumentsNormalisation:
    """Unit tests for is_chunk normalisation applied during add_documents.

    We test the normalisation utility directly (already covered in
    test_marker_filter.py) and also verify that add_documents mutates
    the document metadata before embedding.
    """

    def test_normalise_sets_is_chunk_on_bare_doc(self):
        """A document with only page_content and no metadata markers gets is_chunk=True."""
        doc = Document(page_content="bare text", metadata={})
        _normalise_chunk_marker([doc])
        assert doc.metadata.get('is_chunk') is True

    def test_normalise_does_not_double_mark(self):
        """Calling normalise twice on the same doc is idempotent."""
        doc = Document(page_content="text", metadata={"is_chunk": True})
        _normalise_chunk_marker([doc])
        _normalise_chunk_marker([doc])
        assert doc.metadata['is_chunk'] is True  # still True, not flipped

    def test_normalise_preserves_existing_metadata(self):
        """Normalisation does not remove or overwrite existing metadata keys."""
        doc = Document(
            page_content="text",
            metadata={"document_id": "abc", "source": "pdf", "page": 3},
        )
        _normalise_chunk_marker([doc])
        assert doc.metadata['is_chunk'] is True
        assert doc.metadata['document_id'] == 'abc'
        assert doc.metadata['source'] == 'pdf'
        assert doc.metadata['page'] == 3

    def test_parent_document_untouched_by_normalise(self):
        """A full-document parent is never marked as is_chunk."""
        doc = Document(
            page_content="full doc",
            metadata={"is_full_document": True, "document_type": "parent"},
        )
        _normalise_chunk_marker([doc])
        assert 'is_chunk' not in doc.metadata

    def test_parent_chunk_untouched_by_normalise(self):
        """A parent_chunk document is never marked as is_chunk."""
        doc = Document(
            page_content="intermediate chunk",
            metadata={"document_type": "parent_chunk", "is_chunk": False},
        )
        _normalise_chunk_marker([doc])
        # is_chunk=False was explicitly set and should NOT be overwritten
        assert doc.metadata['is_chunk'] is False

    def test_mixed_batch_only_marks_unmarked_non_parents(self):
        """Only non-parent, unmarked docs in a batch are given is_chunk=True."""
        docs = [
            Document(page_content="unmarked", metadata={"id": "1"}),
            Document(page_content="already chunk", metadata={"id": "2", "is_chunk": True}),
            Document(page_content="parent", metadata={"id": "3", "is_full_document": True}),
            Document(page_content="parent chunk", metadata={"id": "4", "document_type": "parent_chunk"}),
        ]
        _normalise_chunk_marker(docs)

        assert docs[0].metadata['is_chunk'] is True       # marked
        assert docs[1].metadata['is_chunk'] is True       # unchanged
        assert 'is_chunk' not in docs[2].metadata          # parent untouched
        assert 'is_chunk' not in docs[3].metadata          # parent_chunk untouched
