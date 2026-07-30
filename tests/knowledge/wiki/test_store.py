"""Tests for the wiki retrieval plane — run against EVERY backend.

The ``store`` fixture is parametrized over both `BaseWikiStore`
implementations (SQLite plane and in-memory + OKF file directory), so
the whole behavioural contract — CRUD, lexical/vector search, edges,
source-slice replacement, lint queries, tree rebuild — is pinned
identically for each.  All tests use real on-disk state under
``tmp_path`` — no mocks: the retrieval plane is fast enough to test
for real.
"""

import os
import sqlite3
from pathlib import Path
from unittest import mock

import aiosqlite
import pytest

from parrot.knowledge.wiki.store import (
    BaseWikiStore,
    WikiPageRecord,
    create_wiki_store,
    estimate_tokens,
    _fts_query,
)


@pytest.fixture(params=["sqlite", "memory"])
def store(tmp_path: Path, request: pytest.FixtureRequest) -> BaseWikiStore:
    """Fresh store of each backend, rooted at tmp_path."""
    return create_wiki_store(
        tmp_path, wiki_name="test-wiki", backend=request.param
    )


def _page(cid: str, **kw) -> WikiPageRecord:
    """Shorthand page-record builder."""
    defaults = {
        "concept_id": cid,
        "node_id": kw.pop("node_id", None),
        "title": kw.pop("title", cid.replace("-", " ").title()),
        "category": kw.pop("category", "concept"),
        "summary": kw.pop("summary", f"Summary of {cid}"),
        "body": kw.pop("body", f"# {cid}\n\nBody of {cid}."),
    }
    defaults.update(kw)
    return WikiPageRecord(**defaults)


class TestHelpers:
    """Unit tests for module-level helpers."""

    def test_estimate_tokens_empty(self):
        assert estimate_tokens("") == 0

    def test_estimate_tokens_positive(self):
        assert estimate_tokens("hello world " * 50) > 0

    def test_fts_query_strips_operators(self):
        """FTS operators and quotes in user input cannot inject syntax."""
        expr = _fts_query('neural OR "networks" NEAR(bad) *')
        # Every token is individually quoted
        assert '"neural"' in expr and '"networks"' in expr
        assert "NEAR(" not in expr and "*" not in expr

    def test_fts_query_empty(self):
        assert _fts_query("!!! ***") == ""


class TestPagesCrud:
    """Page upsert / get / list / delete round-trips."""

    @pytest.mark.asyncio
    async def test_upsert_and_get(self, store: BaseWikiStore):
        await store.upsert_pages([_page("intro", node_id="0001")])
        page = await store.get_page("intro")
        assert page is not None
        assert page["node_id"] == "0001"
        assert page["body"].startswith("# intro")
        assert page["token_count"] > 0  # auto-computed

    @pytest.mark.asyncio
    async def test_get_by_node_id_fallback(self, store: BaseWikiStore):
        await store.upsert_pages([_page("intro", node_id="0001")])
        page = await store.get_page("0001")
        assert page is not None and page["concept_id"] == "intro"

    @pytest.mark.asyncio
    async def test_get_without_body(self, store: BaseWikiStore):
        await store.upsert_pages([_page("intro")])
        page = await store.get_page("intro", include_body=False)
        assert page is not None and "body" not in page

    @pytest.mark.asyncio
    async def test_get_missing(self, store: BaseWikiStore):
        assert await store.get_page("nope") is None

    @pytest.mark.asyncio
    async def test_upsert_is_idempotent(self, store: BaseWikiStore):
        await store.upsert_pages([_page("intro")])
        await store.upsert_pages([_page("intro", title="Updated")])
        page = await store.get_page("intro")
        assert page["title"] == "Updated"
        stats = await store.stats()
        assert stats["pages"] == 1

    @pytest.mark.asyncio
    async def test_list_pages_category_filter(self, store: BaseWikiStore):
        await store.upsert_pages(
            [_page("a", category="entity"), _page("b", category="summary")]
        )
        entities = await store.list_pages(category="entity")
        assert [p["concept_id"] for p in entities] == ["a"]
        assert "body" not in entities[0]  # stubs only

    @pytest.mark.asyncio
    async def test_delete_page_cleans_everything(self, store: BaseWikiStore):
        await store.upsert_pages([_page("a"), _page("b")])
        await store.add_edges([("a", "b", "references")])
        await store.upsert_embedding("a", [0.1, 0.2], model="m")
        assert await store.delete_page("a") is True
        assert await store.get_page("a") is None
        assert await store.neighbors("b") == []
        # FTS must not find the deleted page
        hits = await store.search_fts("Body of a")
        assert all(h["concept_id"] != "a" for h in hits)

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self, store: BaseWikiStore):
        assert await store.delete_page("nope") is False


class TestSearchFts:
    """BM25 lexical search behavior."""

    @pytest.mark.asyncio
    async def test_search_finds_relevant_page(self, store: BaseWikiStore):
        await store.upsert_pages(
            [
                _page("nn", title="Neural Networks",
                      body="A neural network is a computational model."),
                _page("cooking", title="Cooking Pasta",
                      body="Boil water and add salt."),
            ]
        )
        hits = await store.search_fts("neural network model")
        assert hits and hits[0]["concept_id"] == "nn"
        assert "score" in hits[0]

    @pytest.mark.asyncio
    async def test_search_category_prefilter(self, store: BaseWikiStore):
        await store.upsert_pages(
            [
                _page("nn-sum", category="summary", body="neural networks summary"),
                _page("nn-ent", category="entity", body="neural networks entity"),
            ]
        )
        hits = await store.search_fts("neural", category="entity")
        assert [h["concept_id"] for h in hits] == ["nn-ent"]

    @pytest.mark.asyncio
    async def test_search_empty_query(self, store: BaseWikiStore):
        assert await store.search_fts("***") == []

    @pytest.mark.asyncio
    async def test_search_injection_safe(self, store: BaseWikiStore):
        await store.upsert_pages([_page("a")])
        # Must not raise despite FTS syntax in the query
        assert isinstance(await store.search_fts('"; DROP TABLE pages; --'), list)


class TestVectorSearch:
    """Cosine search over the embeddings table."""

    @pytest.mark.asyncio
    async def test_vector_ranking(self, store: BaseWikiStore):
        await store.upsert_pages([_page("a"), _page("b")])
        await store.upsert_embedding("a", [1.0, 0.0], model="m")
        await store.upsert_embedding("b", [0.0, 1.0], model="m")
        hits = await store.search_vector([1.0, 0.1])
        assert hits[0]["concept_id"] == "a"
        assert hits[0]["score"] > hits[1]["score"]

    @pytest.mark.asyncio
    async def test_vector_empty_store(self, store: BaseWikiStore):
        assert await store.search_vector([1.0, 0.0]) == []

    @pytest.mark.asyncio
    async def test_vector_dimension_mismatch_skipped(self, store: BaseWikiStore):
        await store.upsert_pages([_page("a")])
        await store.upsert_embedding("a", [1.0, 0.0, 0.0], model="m")
        assert await store.search_vector([1.0, 0.0]) == []


class TestEdgesAndNeighbors:
    """Typed edges with open-string relations."""

    @pytest.mark.asyncio
    async def test_neighbors_out_in_both(self, store: BaseWikiStore):
        await store.upsert_pages([_page("a"), _page("b")])
        await store.add_edges([("a", "b", "summarizes")])
        out = await store.neighbors("a", direction="out")
        assert len(out) == 1 and out[0]["concept_id"] == "b"
        assert out[0]["rel"] == "summarizes"
        inbound = await store.neighbors("b", direction="in")
        assert len(inbound) == 1 and inbound[0]["concept_id"] == "a"
        both = await store.neighbors("a", direction="both")
        assert len(both) == 1

    @pytest.mark.asyncio
    async def test_neighbors_rel_filter(self, store: BaseWikiStore):
        await store.upsert_pages([_page("a"), _page("b"), _page("c")])
        await store.add_edges(
            [("a", "b", "summarizes"), ("a", "c", "references")]
        )
        hits = await store.neighbors("a", rel="references", direction="out")
        assert [h["concept_id"] for h in hits] == ["c"]

    @pytest.mark.asyncio
    async def test_open_string_relation(self, store: BaseWikiStore):
        """rel is an open string — no enum gate in the machine plane."""
        await store.upsert_pages([_page("a"), _page("b")])
        await store.add_edges([("a", "b", "totally-custom-rel")])
        hits = await store.neighbors("a", rel="totally-custom-rel")
        assert len(hits) == 1


class TestReplaceSourceSlice:
    """Re-ingest must never accumulate duplicates (fixes G9)."""

    @pytest.mark.asyncio
    async def test_replace_deletes_old_slice(self, store: BaseWikiStore):
        p1 = [_page("old-1", source_id="src-1"), _page("old-2", source_id="src-1")]
        await store.replace_source_slice("src-1", p1, [("old-1", "old-2", "references")])
        p2 = [_page("new-1", source_id="src-1")]
        report = await store.replace_source_slice("src-1", p2)
        assert report["pages_deleted"] == 2
        assert report["pages_written"] == 1
        assert await store.get_page("old-1") is None
        assert await store.get_page("new-1") is not None
        stats = await store.stats()
        assert stats["pages"] == 1
        assert stats["edges"] == 0  # old edges cleaned up

    @pytest.mark.asyncio
    async def test_replace_is_idempotent(self, store: BaseWikiStore):
        pages = [_page("p-1", source_id="src-1")]
        await store.replace_source_slice("src-1", pages)
        await store.replace_source_slice("src-1", pages)
        stats = await store.stats()
        assert stats["pages"] == 1

    @pytest.mark.asyncio
    async def test_replace_leaves_other_sources_alone(self, store: BaseWikiStore):
        await store.replace_source_slice("src-1", [_page("a", source_id="src-1")])
        await store.replace_source_slice("src-2", [_page("b", source_id="src-2")])
        await store.replace_source_slice("src-1", [_page("a2", source_id="src-1")])
        assert await store.get_page("b") is not None

    @pytest.mark.asyncio
    async def test_replace_preserves_incoming_edges_to_stable_ids(
        self, store: BaseWikiStore
    ):
        """Incoming edges from other sources survive a re-ingest.

        A directory 'contains' edge (or an importer's 'references'
        edge) points INTO a page whose concept_id is stable across
        re-ingests — replacing the page's source slice must not drop it.
        """
        await store.replace_source_slice("src-1", [_page("a", source_id="src-1")])
        await store.upsert_pages([_page("dir-x")])
        await store.add_edges([("dir-x", "a", "contains")])

        await store.replace_source_slice("src-1", [_page("a", source_id="src-1")])

        incoming = await store.neighbors("a", direction="in")
        assert [(n["concept_id"], n["rel"]) for n in incoming] == [
            ("dir-x", "contains")
        ]

    @pytest.mark.asyncio
    async def test_replace_drops_incoming_edges_to_removed_ids(
        self, store: BaseWikiStore
    ):
        """Incoming edges are NOT preserved when the target id vanishes."""
        await store.replace_source_slice("src-1", [_page("a", source_id="src-1")])
        await store.upsert_pages([_page("dir-x")])
        await store.add_edges([("dir-x", "a", "contains")])

        # Re-ingest produces a different page id — the old edge target
        # is gone, so the edge must be cleaned up (no dangling edges).
        await store.replace_source_slice("src-1", [_page("a2", source_id="src-1")])

        stats = await store.stats()
        assert stats["edges"] == 0


class TestLintQueries:
    """Fast SQL lint checks."""

    @pytest.mark.asyncio
    async def test_broken_edges(self, store: BaseWikiStore):
        await store.upsert_pages([_page("a")])
        await store.add_edges([("a", "ghost", "references")])
        broken = await store.broken_edges()
        assert len(broken) == 1 and broken[0]["dst"] == "ghost"

    @pytest.mark.asyncio
    async def test_missing_bodies(self, store: BaseWikiStore):
        await store.upsert_pages([_page("a", body=""), _page("b")])
        assert await store.missing_bodies() == ["a"]

    @pytest.mark.asyncio
    async def test_stats(self, store: BaseWikiStore):
        await store.upsert_pages([_page("a", category="entity"), _page("b")])
        stats = await store.stats()
        assert stats["pages"] == 2
        assert stats["categories"] == {"entity": 1, "concept": 1}
        assert stats["total_tokens"] > 0


class TestRebuildFromTree:
    """Derived-plane rebuild from a PageIndex tree."""

    @pytest.mark.asyncio
    async def test_rebuild(self, store: BaseWikiStore):
        tree = {
            "structure": [
                {
                    "node_id": "0000",
                    "concept_id": "hipaa",
                    "title": "HIPAA",
                    "summary": "Overview",
                    "nodes": [
                        {
                            "node_id": "0001",
                            "concept_id": "hipaa/safeguards",
                            "title": "Safeguards",
                            "summary": "Admin safeguards",
                            "nodes": [],
                        }
                    ],
                }
            ]
        }
        bodies = {"hipaa": "# HIPAA\n\nfull text", "0001": "# Safeguards"}
        report = await store.rebuild_from_tree(
            tree, content_loader=bodies.get, source_id="src-1"
        )
        assert report["pages_written"] == 2
        root = await store.get_page("hipaa")
        assert root["body"] == "# HIPAA\n\nfull text"
        child = await store.get_page("hipaa/safeguards")
        # body found via node_id fallback in the loader
        assert child["body"] == "# Safeguards"
        assert child["source_id"] == "src-1"

    @pytest.mark.asyncio
    async def test_rebuild_without_loader(self, store: BaseWikiStore):
        tree = {"structure": [{"node_id": "0000", "title": "T", "summary": "s", "nodes": []}]}
        report = await store.rebuild_from_tree(tree)
        assert report["pages_written"] == 1
        page = await store.get_page("0000")  # falls back to node_id identity
        assert page is not None and page["body"] == ""


_skip_root = pytest.mark.skipif(
    os.geteuid() == 0, reason="chmod is a no-op for root"
)


class TestReadOnlyFallback:
    """An existing SQLite plane stays queryable on a read-only filesystem.

    Read-only review sandboxes (e.g. `codex exec review`) deny all writes;
    the WAL journal + schema replay used to make even pure queries die
    with ``sqlite3.OperationalError: unable to open database file``.
    """

    @pytest.fixture()
    async def ro_plane(self, tmp_path: Path):
        """A populated plane whose directory is then made read-only."""
        store = create_wiki_store(tmp_path, wiki_name="ro", backend="sqlite")
        await store.upsert_pages(
            [_page("ro-page", body="# ro\n\nneedle haystack content")]
        )
        db = tmp_path / "wiki.db"
        db.chmod(0o444)
        tmp_path.chmod(0o555)
        try:
            yield tmp_path
        finally:
            tmp_path.chmod(0o755)
            db.chmod(0o644)

    @_skip_root
    @pytest.mark.asyncio
    async def test_reads_survive_readonly_fs(self, ro_plane: Path):
        store = create_wiki_store(ro_plane, wiki_name="ro", backend="sqlite")
        page = await store.get_page("ro-page")
        assert page is not None and "needle" in page["body"]
        hits = await store.search_fts("needle", limit=5)
        assert [h["concept_id"] for h in hits] == ["ro-page"]

    @_skip_root
    @pytest.mark.asyncio
    async def test_writes_fail_with_readonly_error(self, ro_plane: Path):
        store = create_wiki_store(ro_plane, wiki_name="ro", backend="sqlite")
        await store.get_page("ro-page")  # flips the store into ro mode
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            await store.upsert_pages([_page("nope")])

    @_skip_root
    @pytest.mark.asyncio
    async def test_missing_db_still_raises(self, tmp_path: Path):
        """A genuinely absent database is never masked by the fallback."""
        sub = tmp_path / "empty"
        sub.mkdir()
        sub.chmod(0o555)
        try:
            store = create_wiki_store(sub, wiki_name="ro", backend="sqlite")
            with pytest.raises(sqlite3.OperationalError):
                await store.get_page("anything")
        finally:
            sub.chmod(0o755)

    @pytest.mark.asyncio
    async def test_transient_errors_propagate_and_recover(self, tmp_path: Path):
        """A lock/transient failure propagates; the store stays writable."""
        store = create_wiki_store(tmp_path, wiki_name="w", backend="sqlite")
        await store.upsert_pages([_page("p1")])
        fresh = create_wiki_store(tmp_path, wiki_name="w", backend="sqlite")

        def locked(self, sql):
            raise sqlite3.OperationalError("database is locked")

        with mock.patch.object(
            aiosqlite.Connection, "executescript", locked
        ):
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                await fresh.get_page("p1")
        # The store recovers once the contention is gone — including writes.
        assert await fresh.get_page("p1") is not None
        await fresh.upsert_pages([_page("p2")])

    @_skip_root
    @pytest.mark.asyncio
    async def test_writable_again_heals_write_path(self, tmp_path: Path):
        """Degradation is not sticky: a plane that becomes writable again
        serves writes without a new store instance."""
        store = create_wiki_store(tmp_path, wiki_name="w", backend="sqlite")
        await store.upsert_pages([_page("p1")])
        (tmp_path / "wiki.db").chmod(0o444)
        tmp_path.chmod(0o555)
        try:
            fresh = create_wiki_store(
                tmp_path, wiki_name="w", backend="sqlite"
            )
            assert await fresh.get_page("p1") is not None  # degraded read
        finally:
            tmp_path.chmod(0o755)
            (tmp_path / "wiki.db").chmod(0o644)
        await fresh.upsert_pages([_page("p2")])
        assert await fresh.get_page("p2") is not None

    @_skip_root
    @pytest.mark.asyncio
    async def test_concurrent_writer_served_by_locking_ro_path(
        self, tmp_path: Path
    ):
        """With live -wal/-shm sidecars from a real writer, reads go
        through plain mode=ro (full locking) and SEE the WAL content."""
        store = create_wiki_store(tmp_path, wiki_name="w", backend="sqlite")
        await store.upsert_pages([_page("p1")])
        writer = sqlite3.connect(tmp_path / "wiki.db")
        try:
            writer.execute(
                "UPDATE pages SET summary = 'from-writer'"
                " WHERE concept_id = 'p1'"
            )
            writer.commit()  # committed into the WAL, not yet checkpointed
            assert (tmp_path / "wiki.db-wal").stat().st_size > 0
            (tmp_path / "wiki.db").chmod(0o444)
            tmp_path.chmod(0o555)
            fresh = create_wiki_store(
                tmp_path, wiki_name="w", backend="sqlite"
            )
            page = await fresh.get_page("p1")
            assert page is not None
            assert page["summary"] == "from-writer"
        finally:
            tmp_path.chmod(0o755)
            (tmp_path / "wiki.db").chmod(0o644)
            writer.close()

    @_skip_root
    @pytest.mark.asyncio
    async def test_live_wal_refuses_immutable_fallback(self, tmp_path: Path):
        """A non-empty -wal holds committed data an immutable reader would
        silently miss — the store must raise instead of serving it."""
        store = create_wiki_store(tmp_path, wiki_name="w", backend="sqlite")
        await store.upsert_pages([_page("p1")])
        (tmp_path / "wiki.db-wal").write_bytes(b"\x00" * 32)
        (tmp_path / "wiki.db").chmod(0o444)
        tmp_path.chmod(0o555)
        try:
            fresh = create_wiki_store(
                tmp_path, wiki_name="w", backend="sqlite"
            )
            with pytest.raises(sqlite3.OperationalError):
                await fresh.get_page("p1")
        finally:
            tmp_path.chmod(0o755)
            (tmp_path / "wiki.db").chmod(0o644)

    @pytest.mark.asyncio
    async def test_schema_ensured_once_per_store(self, tmp_path: Path):
        """The schema replay runs on the first connection only."""
        store = create_wiki_store(tmp_path, wiki_name="w", backend="sqlite")
        await store.upsert_pages([_page("p1")])
        assert store._schema_ready is True
        scripts: list[str] = []
        orig = aiosqlite.Connection.executescript

        def spy(self, sql):
            scripts.append(sql)
            return orig(self, sql)

        with mock.patch.object(aiosqlite.Connection, "executescript", spy):
            assert await store.get_page("p1") is not None
        assert scripts == []
