"""Live-DB-gated tests for PostgresWikiStore (FEAT-520 TASK-2768).

Covers the full BaseWikiStore abstract surface against Postgres directly
(there is no existing cross-backend `test_store.py` parametrized suite in
this codebase to extend — see the task's Codebase Contract correction),
plus Postgres-specific behavior: caller-preserving `updated_at`,
close-and-insert versioning, and graph/wiki plane coexistence on the
shared `graphindex.*` schema.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from parrot.conf import default_dsn
from parrot.knowledge.graphindex import pg_schema
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence
from parrot.knowledge.graphindex.schema import NodeKind, UniversalNode
from parrot.knowledge.wiki.postgres_store import PostgresWikiStore
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store

PG_DSN = os.environ.get("GRAPHINDEX_PG_DSN") or default_dsn
pytestmark = pytest.mark.skipif(not PG_DSN, reason="needs live Postgres")


def make_page(concept_id: str, **kwargs: Any) -> WikiPageRecord:
    kwargs.setdefault("title", f"Page {concept_id}")
    kwargs.setdefault("body", f"Body of {concept_id}")
    return WikiPageRecord(concept_id=concept_id, **kwargs)


@pytest.fixture
def tmp_schema() -> str:
    return f"graphindex_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture
async def pg_wiki_store(tmp_schema):
    store = PostgresWikiStore(PG_DSN, wiki_name="test-wiki", schema=tmp_schema)
    try:
        yield store
    finally:
        pool = await store._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {tmp_schema} CASCADE")
        await store.close()


@pytest.fixture
async def pg_persistence(pg_wiki_store, tmp_schema):
    """Graph-plane store over the SAME schema the wiki fixture owns."""
    persistence = PostgresPersistence(PG_DSN, schema=tmp_schema)
    try:
        yield persistence
    finally:
        await persistence.close()


def _make_ctx(tenant_id: str = "test_tenant") -> Any:
    ctx = MagicMock()
    ctx.tenant_id = tenant_id
    return ctx


# ---------------------------------------------------------------------------
# Write / read roundtrip
# ---------------------------------------------------------------------------


async def test_upsert_and_get_page(pg_wiki_store):
    written = await pg_wiki_store.upsert_pages([make_page("p1", summary="s1")])
    assert written == 1

    page = await pg_wiki_store.get_page("p1")
    assert page["concept_id"] == "p1"
    assert page["title"] == "Page p1"
    assert page["body"] == "Body of p1"
    assert page["summary"] == "s1"


async def test_get_page_excludes_body_when_not_requested(pg_wiki_store):
    await pg_wiki_store.upsert_pages([make_page("p1")])
    page = await pg_wiki_store.get_page("p1", include_body=False)
    assert "body" not in page


async def test_get_page_falls_back_to_node_id(pg_wiki_store):
    await pg_wiki_store.upsert_pages([make_page("p1", node_id="volatile-1")])
    page = await pg_wiki_store.get_page("volatile-1")
    assert page["concept_id"] == "p1"


async def test_get_page_unknown_returns_none(pg_wiki_store):
    assert await pg_wiki_store.get_page("nope") is None


async def test_updated_at_caller_preserved(pg_wiki_store):
    stamp = "2020-01-01T00:00:00+00:00"
    await pg_wiki_store.upsert_pages([make_page("p1", updated_at=stamp)])
    page = await pg_wiki_store.get_page("p1")
    assert page["updated_at"] == stamp


async def test_updated_at_none_stamps_now(pg_wiki_store):
    # _fmt_ts truncates to whole seconds (house ISO convention) — allow a
    # 1s tolerance either side rather than asserting sub-second ordering.
    before = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
    await pg_wiki_store.upsert_pages([make_page("p1")])
    page = await pg_wiki_store.get_page("p1")
    stamped = datetime.fromisoformat(page["updated_at"])
    assert stamped >= before


async def test_upsert_change_creates_version(pg_wiki_store, pg_persistence):
    ctx = _make_ctx()
    await pg_wiki_store.upsert_pages([make_page("p1", body="v1")])
    await pg_wiki_store.upsert_pages([make_page("p1", body="v2")])

    history = await pg_persistence.history(ctx, "p1")
    assert [row.body for row in history] == ["v1", "v2"]
    assert history[0].valid_to is not None
    assert history[1].valid_to is None


async def test_add_edges_and_neighbors(pg_wiki_store):
    await pg_wiki_store.upsert_pages([make_page("a"), make_page("b")])
    written = await pg_wiki_store.add_edges([("a", "b", "links_to")])
    assert written == 1

    out = await pg_wiki_store.neighbors("a", direction="out")
    assert [(n["concept_id"], n["rel"], n["direction"]) for n in out] == [("b", "links_to", "out")]

    inbound = await pg_wiki_store.neighbors("b", direction="in")
    assert [(n["concept_id"], n["direction"]) for n in inbound] == [("a", "in")]


async def test_add_edges_with_provenance(pg_wiki_store):
    await pg_wiki_store.upsert_pages([make_page("a"), make_page("b")])
    await pg_wiki_store.add_edges([("a", "b", "asserts", "asserted")])
    neighbors = await pg_wiki_store.neighbors("a")
    assert neighbors[0]["provenance"] == "asserted"


async def test_replace_source_slice_atomic(pg_wiki_store):
    await pg_wiki_store.upsert_pages([make_page("p1", source_id="doc://a"), make_page("p2", source_id="doc://a")])
    result = await pg_wiki_store.replace_source_slice("doc://a", [make_page("p3", source_id="doc://a")])
    assert result["pages_deleted"] == 2
    assert result["pages_written"] == 1

    assert await pg_wiki_store.get_page("p1") is None
    assert await pg_wiki_store.get_page("p2") is None
    assert (await pg_wiki_store.get_page("p3"))["concept_id"] == "p3"


async def test_delete_page_closes_validity(pg_wiki_store):
    await pg_wiki_store.upsert_pages([make_page("p1")])
    assert await pg_wiki_store.delete_page("p1") is True
    assert await pg_wiki_store.get_page("p1") is None
    assert await pg_wiki_store.delete_page("p1") is False  # already closed


async def test_upsert_embedding_and_search_vector(pg_wiki_store):
    await pg_wiki_store.upsert_pages([make_page("p1")])
    dim = pg_schema.GRAPHINDEX_EMBEDDING_DIM
    vec = [0.1] * dim
    await pg_wiki_store.upsert_embedding("p1", vec, model="test-model")

    results = await pg_wiki_store.search_vector(vec, limit=5)
    assert len(results) == 1
    assert results[0]["concept_id"] == "p1"
    assert results[0]["score"] == pytest.approx(1.0, abs=1e-3)


async def test_list_pages_filters(pg_wiki_store):
    await pg_wiki_store.upsert_pages(
        [
            make_page("p1", category="concept", origin="ingest"),
            make_page("p2", category="summary", origin="memory"),
        ]
    )
    by_category = await pg_wiki_store.list_pages(category="summary")
    assert [p["concept_id"] for p in by_category] == ["p2"]

    by_origin = await pg_wiki_store.list_pages(origin=["memory"])
    assert [p["concept_id"] for p in by_origin] == ["p2"]


async def test_search_fts_excludes_archive_by_default(pg_wiki_store):
    await pg_wiki_store.upsert_pages(
        [
            make_page("p1", title="quantum computing", body="quantum computing basics"),
            make_page("p2", title="quantum archive", body="quantum computing archived", category="archive"),
        ]
    )
    hits = await pg_wiki_store.search_fts("quantum")
    ids = {h["concept_id"] for h in hits}
    assert "p1" in ids
    assert "p2" not in ids

    archive_hits = await pg_wiki_store.search_fts("quantum", category="archive")
    assert {h["concept_id"] for h in archive_hits} == {"p2"}


async def test_dump_pages_and_edges(pg_wiki_store):
    await pg_wiki_store.upsert_pages([make_page("p1"), make_page("p2")])
    await pg_wiki_store.add_edges([("p1", "p2", "links_to")])

    pages = await pg_wiki_store.dump_pages()
    assert {p["concept_id"] for p in pages} == {"p1", "p2"}
    assert all("body" in p for p in pages)

    edges = await pg_wiki_store.dump_edges()
    assert [(e["src"], e["dst"], e["rel"]) for e in edges] == [("p1", "p2", "links_to")]


async def test_stats(pg_wiki_store):
    await pg_wiki_store.upsert_pages([make_page("p1", category="concept"), make_page("p2", category="concept")])
    await pg_wiki_store.add_edges([("p1", "p2", "links_to")])

    stats = await pg_wiki_store.stats()
    assert stats["pages"] == 2
    assert stats["edges"] == 1
    assert stats["categories"] == {"concept": 2}
    assert stats["symbols"] == 0


async def test_orphan_sources_always_empty(pg_wiki_store):
    """No sources registry in the shared schema — documented, not a bug."""
    assert await pg_wiki_store.orphan_sources() == []


async def test_broken_edges(pg_wiki_store):
    await pg_wiki_store.upsert_pages([make_page("p1")])
    await pg_wiki_store.add_edges([("p1", "does-not-exist", "links_to")])
    broken = await pg_wiki_store.broken_edges()
    assert [(b["src"], b["dst"]) for b in broken] == [("p1", "does-not-exist")]


async def test_missing_bodies(pg_wiki_store):
    await pg_wiki_store.upsert_pages([make_page("p1", body=""), make_page("p2", body="has content")])
    missing = await pg_wiki_store.missing_bodies()
    assert missing == ["p1"]


async def test_page_hashes(pg_wiki_store):
    await pg_wiki_store.upsert_pages([make_page("p1", content_hash="abc123")])
    hashes = await pg_wiki_store.page_hashes(["p1", "unknown"])
    assert hashes == {"p1": "abc123", "unknown": None}


# ---------------------------------------------------------------------------
# Graph / wiki plane coexistence (spec AC)
# ---------------------------------------------------------------------------


async def test_planes_coexist(pg_wiki_store, pg_persistence):
    """A graph node and a wiki page with different concept_ids don't interfere.

    Both planes write into the SAME ``nodes``/``node_versions`` tables
    (spec U1), so isolation is enforced two different ways depending on
    the read path:

    - ``load_graph`` (graph plane) excludes the wiki-only row because its
      ``nodes.category`` (an open string — here ``"summary"``, a real
      wiki category that is NOT a ``NodeKind`` value) fails to coerce to
      the enum — skip-and-warn, the same forward-compat tolerance the
      SQLite/Arango siblings use for unknown kinds. The AC's own wording
      ("unless their category is a valid NodeKind") accepts that a wiki
      category which HAPPENS to collide with a real ``NodeKind`` string
      (e.g. ``"concept"``, ``"document"``) would show up — that is the
      decided, documented boundary of this filter, not a bug to further
      mitigate.
    - ``list_pages``/``dump_pages``/``stats`` (wiki plane, enumeration
      reads) are explicitly scoped to ``nodes.namespace = wiki_name``
      (this store's own namespace convention, see module docstring) — so
      they never enumerate the graph plane's rows even though a direct
      ``get_page(concept_id)`` identity lookup is namespace-agnostic by
      design (concept_id is the shared, globally-unique key).
    """
    ctx = _make_ctx()
    graph_node = UniversalNode(node_id="g1", kind=NodeKind.DOCUMENT, title="Graph node", source_uri="g.txt")
    await pg_persistence.persist_graph(ctx, [graph_node], [])
    await pg_wiki_store.upsert_pages([make_page("w1", category="summary")])

    nodes, _ = await pg_persistence.load_graph(ctx)
    assert {n.node_id for n in nodes} == {"g1"}

    wiki_pages = await pg_wiki_store.list_pages()
    assert {p["concept_id"] for p in wiki_pages} == {"w1"}


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


def test_factory_postgres_branch(tmp_path):
    store = create_wiki_store(tmp_path, wiki_name="w", backend="postgres", dsn=PG_DSN)
    assert isinstance(store, PostgresWikiStore)


def test_factory_unknown_backend_lists_postgres(tmp_path):
    with pytest.raises(ValueError, match="postgres"):
        create_wiki_store(tmp_path, backend="totally-unknown")


def test_no_sqlalchemy_imports():
    import parrot.knowledge.wiki.postgres_store as module

    with open(module.__file__, "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "sqlalchemy" not in content.lower()
