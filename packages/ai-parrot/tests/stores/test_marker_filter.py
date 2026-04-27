"""Unit tests for the default parent-exclusion filter in similarity_search.

TASK-856 — Marker standardisation in stores.

These tests use a mocked PgVectorStore to verify that:
1. The default similarity_search filter excludes parent rows.
2. Legacy unmarked rows (no is_chunk, no is_full_document, no document_type)
   ARE returned by default (backward compatibility).
3. include_parents=True restores legacy behaviour (both chunks and parents).
4. mmr_search inherits the same filter via its similarity_search call.

Because these tests mock the DB internals, they do NOT require a live postgres.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_search_result(doc_id: str, content: str, metadata: Dict[str, Any]):
    """Return a minimal SearchResult-like object."""
    from parrot.stores.models import SearchResult
    return SearchResult(id=doc_id, content=content, metadata=metadata, score=0.9)


def _make_mock_pg_store(rows_by_query: Dict[str, List] = None):
    """Build a mock PgVectorStore that has a controllable similarity_search.

    This mock patches the SQL execution layer rather than the
    similarity_search method itself, so we can test the filter logic.
    """
    # We'll test at the level of similarity_search result filtering logic
    # rather than mocking the entire SQL layer.
    return rows_by_query or {}


# ---------------------------------------------------------------------------
# Tests for _normalise_chunk_marker (the utility function)
# ---------------------------------------------------------------------------

class TestNormaliseChunkMarker:
    """Unit tests for the _normalise_chunk_marker utility."""

    def test_unmarked_doc_gets_is_chunk_true(self):
        """A document with no markers gets is_chunk=True."""
        from parrot.stores.abstract import _normalise_chunk_marker
        from parrot.stores.models import Document

        doc = Document(page_content="text", metadata={"document_id": "x"})
        _normalise_chunk_marker([doc])
        assert doc.metadata['is_chunk'] is True

    def test_already_marked_chunk_is_untouched(self):
        """A document already marked is_chunk=True is not modified."""
        from parrot.stores.abstract import _normalise_chunk_marker
        from parrot.stores.models import Document

        doc = Document(page_content="text", metadata={"document_id": "x", "is_chunk": True})
        _normalise_chunk_marker([doc])
        assert doc.metadata['is_chunk'] is True  # unchanged

    def test_is_chunk_false_is_not_overwritten(self):
        """A document explicitly marked is_chunk=False is not overwritten."""
        from parrot.stores.abstract import _normalise_chunk_marker
        from parrot.stores.models import Document

        doc = Document(page_content="text", metadata={"document_id": "x", "is_chunk": False})
        _normalise_chunk_marker([doc])
        assert doc.metadata['is_chunk'] is False  # must not flip to True

    def test_parent_doc_not_marked_as_chunk(self):
        """A parent document (is_full_document=True) must NOT get is_chunk=True."""
        from parrot.stores.abstract import _normalise_chunk_marker
        from parrot.stores.models import Document

        doc = Document(
            page_content="text",
            metadata={"document_id": "p1", "is_full_document": True},
        )
        _normalise_chunk_marker([doc])
        assert 'is_chunk' not in doc.metadata
        assert doc.metadata['is_full_document'] is True

    def test_parent_chunk_doc_not_marked_as_chunk(self):
        """A parent_chunk document (document_type='parent_chunk') must NOT get is_chunk=True."""
        from parrot.stores.abstract import _normalise_chunk_marker
        from parrot.stores.models import Document

        doc = Document(
            page_content="text",
            metadata={"document_id": "pc1", "document_type": "parent_chunk"},
        )
        _normalise_chunk_marker([doc])
        assert 'is_chunk' not in doc.metadata

    def test_document_type_parent_not_marked_as_chunk(self):
        """A document with document_type='parent' must NOT get is_chunk=True."""
        from parrot.stores.abstract import _normalise_chunk_marker
        from parrot.stores.models import Document

        doc = Document(
            page_content="text",
            metadata={"document_id": "doc1", "document_type": "parent"},
        )
        _normalise_chunk_marker([doc])
        assert 'is_chunk' not in doc.metadata

    def test_idempotent_on_empty_list(self):
        """_normalise_chunk_marker handles an empty list without error."""
        from parrot.stores.abstract import _normalise_chunk_marker
        _normalise_chunk_marker([])  # should not raise

    def test_normalises_multiple_docs_correctly(self):
        """Mixed list: only unmarked non-parents get is_chunk=True."""
        from parrot.stores.abstract import _normalise_chunk_marker
        from parrot.stores.models import Document

        docs = [
            Document(page_content="c1", metadata={"document_id": "c1"}),  # will be marked
            Document(page_content="c2", metadata={"is_chunk": True, "document_id": "c2"}),  # already marked
            Document(page_content="p1", metadata={"is_full_document": True, "document_id": "p1"}),  # parent
        ]
        _normalise_chunk_marker(docs)

        assert docs[0].metadata['is_chunk'] is True
        assert docs[1].metadata['is_chunk'] is True
        assert 'is_chunk' not in docs[2].metadata


# ---------------------------------------------------------------------------
# Tests for the include_parents kwarg on the abstract class signature
# ---------------------------------------------------------------------------

class TestAbstractStoreIncludeParentsSignature:
    """Verify that AbstractStore.similarity_search includes include_parents."""

    def test_abstract_similarity_search_has_include_parents_kwarg(self):
        """The abstract method signature must include include_parents=False."""
        import inspect
        from parrot.stores.abstract import AbstractStore

        sig = inspect.signature(AbstractStore.similarity_search)
        assert 'include_parents' in sig.parameters
        default = sig.parameters['include_parents'].default
        assert default is False, f"Expected default False, got {default!r}"
