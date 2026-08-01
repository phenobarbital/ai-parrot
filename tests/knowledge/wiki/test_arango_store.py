"""Unit tests for ArangoDBWikiStore (FEAT-400, TASK-2057).

All tests mock ``asyncdb.AsyncDB`` — no real ArangoDB server is needed
(that is covered by the integration tests in TASK-2063). The mocked
driver mirrors ``asyncdb.drivers.arangodb.arangodb``'s real return
shapes:

- ``query()`` / ``execute()`` return a ``(result, error)`` pair (a list
  and an optional error string) — NOT a raised exception.
- ``collection_exists()`` / ``create_collection()`` /
  ``create_arangosearch_view()`` / ``connection()`` / ``close()`` are
  plain async calls.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from parrot.knowledge.wiki.arango_store import (
    EDGES_COLLECTION,
    EMBEDDINGS_COLLECTION,
    META_COLLECTION,
    PAGES_COLLECTION,
    SOURCES_COLLECTION,
    ArangoDBWikiStore,
)
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord


def _page(cid: str, **kw) -> WikiPageRecord:
    """Shorthand page-record builder (mirrors test_store.py's helper)."""
    defaults = {
        "concept_id": cid,
        "title": kw.pop("title", cid.replace("-", " ").title()),
        "category": kw.pop("category", "concept"),
        "summary": kw.pop("summary", f"Summary of {cid}"),
        "body": kw.pop("body", f"# {cid}\n\nBody of {cid}."),
    }
    defaults.update(kw)
    return WikiPageRecord(**defaults)


@pytest.fixture
def arango_params():
    """ArangoDB connection params for a (mocked) test instance."""
    return {"host": "127.0.0.1", "port": 8529, "username": "root", "password": ""}


@pytest.fixture
def mock_db():
    """Mocked ``asyncdb`` ArangoDB driver instance."""
    db = MagicMock()
    db.connection = AsyncMock(return_value=db)
    db.close = AsyncMock()
    db.collection_exists = AsyncMock(return_value=False)
    db.create_collection = AsyncMock()
    db.create_arangosearch_view = AsyncMock()
    db.query = AsyncMock(return_value=([], None))
    db.execute = AsyncMock(return_value=([], None))
    return db


@pytest.fixture
def store(arango_params, mock_db):
    """``ArangoDBWikiStore`` with ``AsyncDB`` patched to return ``mock_db``."""
    with patch("parrot.knowledge.wiki.arango_store.AsyncDB", return_value=mock_db):
        yield ArangoDBWikiStore(arango_params, wiki_name="test")


class TestArangoDBWikiStore:
    """Construction, lifecycle, and BaseWikiStore contract."""

    def test_inherits_base_wiki_store(self, store):
        assert isinstance(store, BaseWikiStore)

    def test_init(self, store):
        assert store._wiki_name == "test"
        assert store._database == "wiki_test"
        assert not store._initialized
        assert store.database == "wiki_test"

    def test_init_default_database_from_wiki_name(self, arango_params):
        store = ArangoDBWikiStore(arango_params)
        assert store._database == "wiki_codebase"

    def test_init_explicit_database_overrides_default(self, arango_params):
        store = ArangoDBWikiStore(arango_params, database="custom_db", wiki_name="test")
        assert store._database == "custom_db"

    def test_view_name(self, store):
        assert store._view_name == "test_pages_view"

    @pytest.mark.asyncio
    async def test_initialize_creates_collections_and_view(self, store, mock_db):
        await store.initialize()

        mock_db.connection.assert_awaited_once()
        assert store._initialized is True

        created = [call.args[0] for call in mock_db.create_collection.call_args_list]
        assert set(created) == {
            PAGES_COLLECTION,
            EDGES_COLLECTION,
            EMBEDDINGS_COLLECTION,
            SOURCES_COLLECTION,
            META_COLLECTION,
        }
        edge_call = next(
            c
            for c in mock_db.create_collection.call_args_list
            if c.args[0] == EDGES_COLLECTION
        )
        assert edge_call.kwargs.get("edge") is True

        mock_db.create_arangosearch_view.assert_awaited_once()
        view_args, view_kwargs = mock_db.create_arangosearch_view.call_args
        assert view_args[0] == "test_pages_view"
        assert PAGES_COLLECTION in view_kwargs["links"]

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, store, mock_db):
        await store.initialize()
        await store.initialize()
        mock_db.connection.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initialize_skips_existing_collections(self, store, mock_db):
        mock_db.collection_exists = AsyncMock(return_value=True)
        await store.initialize()
        mock_db.create_collection.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_close(self, store, mock_db):
        await store.initialize()
        await store.close()
        mock_db.close.assert_awaited_once()
        assert store._db is None
        assert store._initialized is False

    @pytest.mark.asyncio
    async def test_query_no_data_found_returns_empty(self, store, mock_db):
        store._db = mock_db
        mock_db.query = AsyncMock(return_value=(None, "ArangoDB: No Data Found"))
        result = await store._query("FOR doc IN @@collection RETURN doc", {})
        assert result == []

    @pytest.mark.asyncio
    async def test_query_raises_on_real_error(self, store, mock_db):
        store._db = mock_db
        mock_db.query = AsyncMock(return_value=(None, "Connection refused"))
        with pytest.raises(RuntimeError):
            await store._query("FOR doc IN @@collection RETURN doc", {})

    @pytest.mark.asyncio
    async def test_execute_raises_on_error(self, store, mock_db):
        store._db = mock_db
        mock_db.execute = AsyncMock(return_value=(None, "Write failed"))
        with pytest.raises(RuntimeError):
            await store._execute("REMOVE 'x' IN @@collection", {})

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_upsert_pages_empty(self, store, mock_db):
        assert await store.upsert_pages([]) == 0
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upsert_pages(self, store, mock_db):
        pages = [_page("intro"), _page("advanced")]
        written = await store.upsert_pages(pages)
        assert written == 2
        mock_db.execute.assert_awaited_once()
        aql, kwargs = mock_db.execute.call_args.args[0], mock_db.execute.call_args.kwargs
        assert "UPSERT" in aql
        bind_vars = kwargs["bind_vars"]
        assert bind_vars["@collection"] == PAGES_COLLECTION
        assert len(bind_vars["docs"]) == 2
        assert bind_vars["docs"][0]["_key"] == "intro"
        assert bind_vars["docs"][0]["concept_id"] == "intro"

    @pytest.mark.asyncio
    async def test_add_edges_three_tuple(self, store, mock_db):
        written = await store.add_edges([("a", "b", "references")])
        assert written == 1
        bind_vars = mock_db.execute.call_args.kwargs["bind_vars"]
        doc = bind_vars["docs"][0]
        assert doc["_key"] == "a__b__references"
        assert doc["_from"] == f"{PAGES_COLLECTION}/a"
        assert doc["_to"] == f"{PAGES_COLLECTION}/b"
        assert doc["provenance"] == "extracted"

    @pytest.mark.asyncio
    async def test_add_edges_four_tuple(self, store, mock_db):
        await store.add_edges([("a", "b", "references", "asserted")])
        bind_vars = mock_db.execute.call_args.kwargs["bind_vars"]
        assert bind_vars["docs"][0]["provenance"] == "asserted"

    @pytest.mark.asyncio
    async def test_add_edges_empty(self, store, mock_db):
        assert await store.add_edges([]) == 0
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_replace_source_slice(self, store, mock_db):
        mock_db.query = AsyncMock(
            side_effect=[
                (["old1"], None),  # old_ids for source
                (
                    [{"src": "other", "dst": "old1", "rel": "references"}],
                    None,
                ),  # preserved edge candidates
            ]
        )
        mock_db.execute = AsyncMock(return_value=([], None))

        result = await store.replace_source_slice(
            "src-1", [_page("new1")], edges=[("new1", "new1", "self")]
        )

        assert result == {
            "pages_deleted": 1,
            "pages_written": 1,
            "edges_written": 1,
        }
        # 3 deletes (embeddings, edges, pages) + upsert_pages + add_edges(new)
        # + add_edges(preserved) => 5 execute calls total.
        assert mock_db.execute.await_count == 5

    @pytest.mark.asyncio
    async def test_replace_source_slice_no_old_pages(self, store, mock_db):
        mock_db.query = AsyncMock(return_value=([], None))
        result = await store.replace_source_slice("src-1", [_page("new1")])
        assert result["pages_deleted"] == 0
        assert result["pages_written"] == 1

    @pytest.mark.asyncio
    async def test_delete_page_found(self, store, mock_db):
        mock_db.query = AsyncMock(return_value=([{"concept_id": "intro"}], None))
        deleted = await store.delete_page("intro")
        assert deleted is True
        assert mock_db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_delete_page_not_found(self, store, mock_db):
        mock_db.query = AsyncMock(return_value=([], None))
        deleted = await store.delete_page("missing")
        assert deleted is False
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_upsert_embedding(self, store, mock_db):
        await store.upsert_embedding("intro", [0.1, 0.2, 0.3], model="test-model")
        bind_vars = mock_db.execute.call_args.kwargs["bind_vars"]
        assert bind_vars["doc"]["vector"] == [0.1, 0.2, 0.3]
        assert bind_vars["doc"]["model"] == "test-model"
        assert bind_vars["@collection"] == EMBEDDINGS_COLLECTION

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_page_found(self, store, mock_db):
        mock_db.query = AsyncMock(
            return_value=([{"concept_id": "intro", "title": "Intro"}], None)
        )
        page = await store.get_page("intro")
        assert page == {"concept_id": "intro", "title": "Intro"}

    @pytest.mark.asyncio
    async def test_get_page_not_found(self, store, mock_db):
        mock_db.query = AsyncMock(return_value=([], None))
        assert await store.get_page("missing") is None

    @pytest.mark.asyncio
    async def test_get_page_excludes_body_when_requested(self, store, mock_db):
        await store.get_page("intro", include_body=False)
        aql = mock_db.query.call_args.args[0]
        assert "doc.body" not in aql

    @pytest.mark.asyncio
    async def test_list_pages_filters(self, store, mock_db):
        await store.list_pages(category="concept", limit=5, origin=["memory"])
        bind_vars = mock_db.query.call_args.kwargs["bind_vars"]
        assert bind_vars["category"] == "concept"
        assert bind_vars["origin"] == ["memory"]
        assert bind_vars["limit"] == 5

    @pytest.mark.asyncio
    async def test_search_fts(self, store, mock_db):
        mock_db.query = AsyncMock(
            return_value=([{"concept_id": "intro", "score": 4.2}], None)
        )
        results = await store.search_fts("neural networks", limit=5)
        assert results == [{"concept_id": "intro", "score": 4.2}]
        aql = mock_db.query.call_args.args[0]
        assert "test_pages_view" in aql
        assert "BM25" in aql
        bind_vars = mock_db.query.call_args.kwargs["bind_vars"]
        assert bind_vars["query"] == "neural networks"
        assert bind_vars["analyzer"] == "text_en"

    @pytest.mark.asyncio
    async def test_search_fts_category_filter(self, store, mock_db):
        await store.search_fts("query", category="entity")
        bind_vars = mock_db.query.call_args.kwargs["bind_vars"]
        assert bind_vars["category"] == "entity"

    @pytest.mark.asyncio
    async def test_search_vector(self, store, mock_db):
        mock_db.query = AsyncMock(
            return_value=(
                [
                    {
                        "stub": {"concept_id": "a", "title": "A"},
                        "vector": [1.0, 0.0],
                    },
                    {
                        "stub": {"concept_id": "b", "title": "B"},
                        "vector": [0.0, 1.0],
                    },
                ],
                None,
            )
        )
        results = await store.search_vector([1.0, 0.0], limit=5)
        assert results[0]["concept_id"] == "a"
        assert results[0]["score"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_neighbors_both_directions(self, store, mock_db):
        mock_db.query = AsyncMock(
            side_effect=[
                ([{"concept_id": "b", "rel": "references", "title": "B"}], None),
                ([{"concept_id": "c", "rel": "references", "title": "C"}], None),
            ]
        )
        results = await store.neighbors("a", direction="both")
        assert len(results) == 2
        directions = {r["direction"] for r in results}
        assert directions == {"out", "in"}

    @pytest.mark.asyncio
    async def test_neighbors_rel_filter(self, store, mock_db):
        await store.neighbors("a", rel="summarizes", direction="out")
        bind_vars = mock_db.query.call_args.kwargs["bind_vars"]
        assert bind_vars["rel"] == "summarizes"

    @pytest.mark.asyncio
    async def test_dump_pages(self, store, mock_db):
        mock_db.query = AsyncMock(return_value=([{"concept_id": "a"}], None))
        assert await store.dump_pages() == [{"concept_id": "a"}]

    @pytest.mark.asyncio
    async def test_dump_edges(self, store, mock_db):
        mock_db.query = AsyncMock(
            return_value=([{"src": "a", "dst": "b", "rel": "references"}], None)
        )
        assert await store.dump_edges() == [
            {"src": "a", "dst": "b", "rel": "references"}
        ]

    @pytest.mark.asyncio
    async def test_stats(self, store, mock_db):
        mock_db.query = AsyncMock(
            side_effect=[
                ([3], None),  # pages
                ([2], None),  # edges
                ([1], None),  # sources
                ([1], None),  # embeddings
                ([42], None),  # total_tokens
                ([{"category": "concept", "n": 3}], None),  # categories
            ]
        )
        stats = await store.stats()
        assert stats == {
            "pages": 3,
            "edges": 2,
            "sources": 1,
            "embeddings": 1,
            "total_tokens": 42,
            "categories": {"concept": 3},
        }

    # ------------------------------------------------------------------
    # Lint API
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_orphan_sources(self, store, mock_db):
        mock_db.query = AsyncMock(return_value=(["orphan-1"], None))
        assert await store.orphan_sources() == ["orphan-1"]

    @pytest.mark.asyncio
    async def test_broken_edges(self, store, mock_db):
        mock_db.query = AsyncMock(
            return_value=([{"src": "a", "dst": "ghost", "rel": "references"}], None)
        )
        result = await store.broken_edges()
        assert result == [{"src": "a", "dst": "ghost", "rel": "references"}]

    @pytest.mark.asyncio
    async def test_missing_bodies(self, store, mock_db):
        mock_db.query = AsyncMock(return_value=(["stub-1"], None))
        assert await store.missing_bodies() == ["stub-1"]
