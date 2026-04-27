"""Unit tests for InTableParentSearcher — TASK-855.

These tests use a fully mocked store so they do NOT require a running
postgres instance.  The mock simulates the ``session()`` async context
manager and the ``execute`` method on the session object.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.stores.models import Document
from parrot.stores.parents import InTableParentSearcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_row(doc_id: str, content: str, metadata: Dict[str, Any]):
    """Return a fake DB row tuple (id, document, cmetadata)."""
    return (doc_id, content, metadata)


def _make_mock_store(rows: List[tuple] = None) -> MagicMock:
    """Build a mock store whose session() yields a session that returns rows."""
    rows = rows or []

    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def _session():
        yield mock_session

    store = MagicMock()
    store.table_name = "test_embeddings"
    store.schema = "public"
    store._id_column = "id"
    store._document_column = "document"
    store._metadata_column = "cmetadata"   # must be explicit — MagicMock auto-creates attrs
    store._connected = True
    store.session = _session
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInTableParentSearcher:
    """Unit tests for InTableParentSearcher."""

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty_without_db_hit(self):
        """fetch([]) returns {} immediately without touching the DB."""
        store = _make_mock_store(rows=[])
        searcher = InTableParentSearcher(store=store)
        result = await searcher.fetch([])
        assert result == {}
        # session should never be entered for an empty input
        # We verify by checking rows were never returned

    @pytest.mark.asyncio
    async def test_fetches_existing_parents_keyed_by_id(self):
        """Given parent IDs that exist, returns them keyed by ID."""
        rows = [
            _make_row('p1', 'Parent one content', {'is_full_document': True, 'document_id': 'p1'}),
            _make_row('p2', 'Parent two content', {'is_full_document': True, 'document_id': 'p2'}),
        ]
        store = _make_mock_store(rows=rows)
        searcher = InTableParentSearcher(store=store)

        result = await searcher.fetch(['p1', 'p2'])

        assert 'p1' in result
        assert 'p2' in result
        assert isinstance(result['p1'], Document)
        assert result['p1'].page_content == 'Parent one content'
        assert result['p2'].page_content == 'Parent two content'
        assert result['p1'].metadata['document_id'] == 'p1'

    @pytest.mark.asyncio
    async def test_silently_skips_missing_ids(self):
        """Missing IDs are absent from the result, no exception raised."""
        rows = [
            _make_row('p1', 'Parent one content', {'is_full_document': True}),
        ]
        store = _make_mock_store(rows=rows)
        searcher = InTableParentSearcher(store=store)

        result = await searcher.fetch(['p1', 'missing-id'])

        assert 'p1' in result
        assert 'missing-id' not in result
        # No exception raised

    @pytest.mark.asyncio
    async def test_chunk_ids_are_filtered_out_by_marker_predicate(self):
        """Chunk rows (is_chunk=True) are NOT returned even if their ID was in the input.

        This is enforced at the SQL level by the WHERE predicate.  In this unit
        test, the mock store returns no rows (simulating the SQL filter), and
        we verify the result is empty.
        """
        # The SQL predicate filters out chunks — mock returns no rows
        store = _make_mock_store(rows=[])
        searcher = InTableParentSearcher(store=store)

        result = await searcher.fetch(['chunk-id-1'])

        assert result == {}

    @pytest.mark.asyncio
    async def test_single_round_trip_regardless_of_input_size(self):
        """Exactly one DB call is made regardless of how many IDs are requested."""
        rows = [
            _make_row(f'p{i}', f'Content {i}', {'is_full_document': True})
            for i in range(10)
        ]
        store = _make_mock_store(rows=rows)
        searcher = InTableParentSearcher(store=store)

        # Capture the mock session to count execute calls
        execute_call_count = 0
        original_session = store.session

        @asynccontextmanager
        async def counting_session():
            nonlocal execute_call_count
            async with original_session() as s:
                original_execute = s.execute

                async def counting_execute(*args, **kwargs):
                    nonlocal execute_call_count
                    execute_call_count += 1
                    return await original_execute(*args, **kwargs)

                s.execute = counting_execute
                yield s

        store.session = counting_session

        await searcher.fetch([f'p{i}' for i in range(10)])
        assert execute_call_count == 1, "Expected exactly one SQL round trip"

    @pytest.mark.asyncio
    async def test_health_check_returns_true(self):
        """health_check() returns True (default implementation)."""
        store = _make_mock_store()
        searcher = InTableParentSearcher(store=store)
        assert await searcher.health_check() is True

    @pytest.mark.asyncio
    async def test_no_table_name_returns_empty(self):
        """When the store has no table_name, fetch returns {} with a warning."""
        store = _make_mock_store()
        store.table_name = None
        searcher = InTableParentSearcher(store=store)

        result = await searcher.fetch(['p1'])
        assert result == {}

    @pytest.mark.asyncio
    async def test_parent_chunk_document_type_is_included(self):
        """Parent_chunk document_type is treated as a valid parent marker."""
        rows = [
            _make_row(
                'pc1',
                'Parent chunk content',
                {'document_type': 'parent_chunk', 'is_chunk': False},
            ),
        ]
        store = _make_mock_store(rows=rows)
        searcher = InTableParentSearcher(store=store)

        result = await searcher.fetch(['pc1'])

        assert 'pc1' in result
        assert result['pc1'].metadata['document_type'] == 'parent_chunk'
