"""Integration tests for the ArangoDB wiki backend (FEAT-400, TASK-2063).

Exercises the full pipeline against a REAL ArangoDB instance: build →
ingest → FTS search → vector search → source tracking (stale → re-ingest)
→ edge traversal → stats → lint. Unlike every other test module in this
package (mocked ``asyncdb``), these tests need a live server — set
``TEST_ARANGODB_HOST`` (plus optionally ``TEST_ARANGODB_PORT`` /
``TEST_ARANGODB_USERNAME`` / ``TEST_ARANGODB_PASSWORD``) to run them;
otherwise the whole module is skipped cleanly (e.g. in CI without a
provisioned ArangoDB service).

Run locally against a throwaway ArangoDB, e.g.::

    docker run -d -p 8529:8529 -e ARANGO_NO_AUTH=1 arangodb/arangodb
    TEST_ARANGODB_HOST=127.0.0.1 pytest tests/knowledge/wiki/test_arango_integration.py -v
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from parrot.knowledge.wiki.store import WikiPageRecord

pytestmark = [
    pytest.mark.arangodb,
    pytest.mark.skipif(
        not os.environ.get("TEST_ARANGODB_HOST"),
        reason="TEST_ARANGODB_HOST not set — skip ArangoDB integration tests",
    ),
]


def _page(cid: str, **kw: Any) -> WikiPageRecord:
    """Shorthand page-record builder (mirrors test_store.py's helper)."""
    defaults = {
        "concept_id": cid,
        "title": kw.pop("title", cid.replace("-", " ").title()),
        "category": kw.pop("category", "concept"),
        "summary": kw.pop("summary", f"Summary of {cid}"),
        "body": kw.pop("body", f"# {cid}\n\nBody of {cid} about neural networks."),
    }
    defaults.update(kw)
    return WikiPageRecord(**defaults)


class TestArangoBuildAndQuery:
    """Scenario 1/2: pages written, fetched, and found via BM25 FTS."""

    @pytest.mark.asyncio
    async def test_arango_build_and_query(self, arango_test_db):
        store = arango_test_db
        pages = [
            _page("intro", body="An introduction to neural networks and deep learning."),
            _page("advanced", body="Advanced neural network architectures and training."),
        ]
        written = await store.upsert_pages(pages)
        assert written == 2

        page = await store.get_page("intro")
        assert page is not None
        assert page["title"] == "Intro"

        hits = await store.search_fts("neural networks", limit=5)
        assert len(hits) >= 1
        assert {h["concept_id"] for h in hits} <= {"intro", "advanced"}
        assert all("score" in h for h in hits)


class TestArangoIngestRoundtrip:
    """Scenario 3: embeddings stored, ranked via cosine similarity."""

    @pytest.mark.asyncio
    async def test_arango_ingest_roundtrip(self, arango_test_db):
        store = arango_test_db
        await store.upsert_pages([_page("vec-a"), _page("vec-b")])
        await store.upsert_embedding("vec-a", [1.0, 0.0, 0.0], model="test")
        await store.upsert_embedding("vec-b", [0.0, 1.0, 0.0], model="test")

        results = await store.search_vector([1.0, 0.0, 0.0], limit=5)
        assert results
        assert results[0]["concept_id"] == "vec-a"
        assert results[0]["score"] == pytest.approx(1.0, abs=1e-6)


class TestArangoSourceTracking:
    """Scenario 4: add -> stale detection -> re-ingest cycle."""

    @pytest.mark.asyncio
    async def test_source_stale_reingest_cycle(self, arango_test_db, tmp_path: Path):
        from parrot.knowledge.wiki.sources import SourceCollectionManager

        src_file = tmp_path / "article.md"
        src_file.write_text("Original content about neural networks.")

        mgr = SourceCollectionManager(
            tmp_path / "sources", backend="arangodb", arango_db=arango_test_db._db
        )
        entry = mgr.add_source(src_file)
        assert not mgr.is_stale(entry.source_id)

        src_file.write_text(
            "Modified content, substantially different from the original."
        )
        assert mgr.is_stale(entry.source_id)

        updated = mgr.mark_ingested(entry.source_id, ["intro"], status="ingested")
        assert updated is not None
        assert updated.pages_generated == ["intro"]
        assert not mgr.is_stale(entry.source_id)

        assert mgr.find_by_uri(str(src_file)) == entry.source_id
        assert mgr.remove_source(entry.source_id) is True
        assert mgr.get_source(entry.source_id) is None


class TestArangoEdgesStatsAndLint:
    """Scenarios 5/6/7: edge traversal, stats, and lint checks."""

    @pytest.mark.asyncio
    async def test_edge_traversal_neighbors(self, arango_test_db):
        store = arango_test_db
        await store.upsert_pages([_page("edge-a"), _page("edge-b")])
        await store.add_edges([("edge-a", "edge-b", "references")])

        out_neighbors = await store.neighbors("edge-a", direction="out")
        assert len(out_neighbors) == 1
        assert out_neighbors[0]["concept_id"] == "edge-b"
        assert out_neighbors[0]["direction"] == "out"

        in_neighbors = await store.neighbors("edge-b", direction="in")
        assert len(in_neighbors) == 1
        assert in_neighbors[0]["concept_id"] == "edge-a"
        assert in_neighbors[0]["direction"] == "in"

    @pytest.mark.asyncio
    async def test_stats_counts(self, arango_test_db):
        store = arango_test_db
        await store.upsert_pages(
            [
                _page("stat-a", category="concept"),
                _page("stat-b", category="entity"),
            ]
        )
        await store.add_edges([("stat-a", "stat-b", "references")])
        await store.upsert_embedding("stat-a", [0.1, 0.2], model="test")

        stats = await store.stats()
        assert stats["pages"] == 2
        assert stats["edges"] == 1
        assert stats["embeddings"] == 1
        assert stats["categories"] == {"concept": 1, "entity": 1}

    @pytest.mark.asyncio
    async def test_lint_orphan_and_broken_edges_and_missing_bodies(
        self, arango_test_db
    ):
        store = arango_test_db
        await store.upsert_pages([_page("lint-a", body="")])
        await store.add_edges([("lint-a", "does-not-exist", "references")])

        broken = await store.broken_edges()
        assert any(e["dst"] == "does-not-exist" for e in broken)

        missing = await store.missing_bodies()
        assert "lint-a" in missing


class TestArangoCLIBackend:
    """``wikitoolkit build --backend arangodb`` -> ``wikitoolkit query``."""

    def test_arango_cli_backend(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        arango_params: dict[str, Any],
    ):
        from asyncdb import AsyncDB
        from click.testing import CliRunner
        from parrot.knowledge.wiki.cli import wiki

        monkeypatch.setenv("ARANGODB_HOST", str(arango_params["host"]))
        monkeypatch.setenv("ARANGODB_PORT", str(arango_params["port"]))
        monkeypatch.setenv("ARANGODB_USERNAME", str(arango_params["username"]))
        monkeypatch.setenv("ARANGODB_PASSWORD", str(arango_params["password"]))

        (tmp_path / "README.md").write_text(
            "# Demo\n\nA demo project about neural networks.", encoding="utf-8"
        )
        wiki_name = f"cli-test-{uuid.uuid4().hex[:8]}"
        runner = CliRunner()
        db_name = f"wiki_{wiki_name}"
        try:
            build_result = runner.invoke(
                wiki,
                [
                    "build",
                    "--path",
                    str(tmp_path),
                    "--name",
                    wiki_name,
                    "--backend",
                    "arangodb",
                    "--no-git",
                    "--no-graph",
                    "--no-export",
                ],
            )
            assert build_result.exit_code == 0, build_result.output

            query_result = runner.invoke(
                wiki,
                [
                    "query",
                    "neural networks",
                    "--path",
                    str(tmp_path),
                    "--json",
                ],
            )
            assert query_result.exit_code == 0, query_result.output
        finally:
            admin_db = AsyncDB(
                "arangodb", params={**arango_params, "database": "_system"}
            )

            async def _cleanup() -> None:
                await admin_db.connection()
                try:
                    if await admin_db._connection.has_database(db_name):
                        await admin_db.drop_database(db_name)
                finally:
                    await admin_db.close()

            import asyncio

            asyncio.run(_cleanup())
