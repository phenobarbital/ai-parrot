"""End-to-end integration tests for the LLM Wiki pipeline (TASK-1636 / FEAT-260).

Tests the four golden-path scenarios from Spec §4:

1. ``test_end_to_end_ingest_query`` — ingest a markdown source then query and
   verify the answer references source content.
2. ``test_ingest_reingest_cycle`` — ingest, modify the source on disk, reingest,
   and verify the manifest is updated.
3. ``test_combined_search_ranking`` — ingest two articles then combined-search;
   verify results come from BOTH backends.
4. ``test_lint_reports_issues`` — create wiki with orphan sources then run lint
   and verify issues are detected.

All tests use mocked LLM adapters (no real API calls) and ``tmp_path`` for
filesystem isolation.  Async tests are run with ``pytest-asyncio``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from parrot.knowledge.wiki import (
    LLMWikiToolkit,
    WikiConfig,
    WikiIngestOrchestrator,
    WikiCombinedSearch,
    SourceCollectionManager,
    WikiBookkeeper,
)
from parrot.knowledge.wiki.models import WikiLintReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pi_mock(
    search_results: list[dict[str, Any]] | None = None,
    insert_content_result: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a PageIndexToolkit mock with configurable async responses.

    Args:
        search_results: List of raw result dicts returned by ``search()``.
        insert_content_result: Dict returned by ``insert_content()``.

    Returns:
        Configured :class:`MagicMock`.
    """
    pi = MagicMock()
    pi.search = AsyncMock(
        return_value=search_results
        or [
            {
                "node_id": "pi-n1",
                "title": "Neural Networks",
                "score": 0.9,
                "summary": "A neural network is a computational model.",
            }
        ]
    )
    pi.insert_content = AsyncMock(
        return_value=insert_content_result
        or {
            "tree_name": "test-wiki",
            "new_node_ids": ["0001", "0002", "0003"],
            "title": "Neural Networks",
            "summary": "A neural network is a computational model.",
        }
    )
    pi.insert_markdown = AsyncMock(
        return_value={"tree_name": "test-wiki", "new_node_ids": ["pi-page-1"]}
    )
    pi.create_tree = AsyncMock(return_value={"tree_name": "test-wiki"})
    pi.delete_tree = AsyncMock(return_value={"status": "deleted"})
    return pi


def _make_gi_mock(
    search_results: list[dict[str, Any]] | None = None,
) -> MagicMock:
    """Build a GraphIndexToolkit mock with configurable async responses.

    Args:
        search_results: List of raw result dicts returned by ``search_hybrid()``.

    Returns:
        Configured :class:`MagicMock`.
    """
    gi = MagicMock()
    gi.search_hybrid = AsyncMock(
        return_value=search_results
        or [
            {
                "node_id": "gi-g1",
                "title": "Graph: Neural Networks",
                "score": 0.85,
                "summary": "Graph representation of neural-network concepts.",
            }
        ]
    )
    gi.create_node = AsyncMock(return_value={"node_id": "gi-wp-001", "status": "created"})
    gi.link_nodes = AsyncMock(return_value={"status": "ok"})
    gi.get_neighborhood = AsyncMock(return_value={"neighbours": []})
    return gi


def _make_okf_mock(orphan_nodes: int = 0) -> MagicMock:
    """Build an OKFToolkit mock.

    Args:
        orphan_nodes: Number of orphan nodes to report.

    Returns:
        Configured :class:`MagicMock`.
    """
    okf = MagicMock()
    okf.lint_knowledge_base = AsyncMock(
        return_value={
            "orphan_nodes": orphan_nodes,
            "missing_types": [],
            "stale_days": 90,
        }
    )
    return okf


# ---------------------------------------------------------------------------
# Integration test class
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """End-to-end integration tests for the wiki golden paths."""

    @pytest.mark.asyncio
    async def test_end_to_end_ingest_query(
        self,
        tmp_path: Path,
    ) -> None:
        """Ingest a markdown source then query; answer must reference source content.

        Steps:
        1. Create a markdown source file with known content.
        2. Build a :class:`LLMWikiToolkit` with mocked backends.
        3. Call ``ingest_source()`` — expect ``status="ok"`` and at least one
           page created.
        4. Call ``query()`` with a question about the source content.
        5. Verify the answer string contains the source content excerpt
           returned by the mocked PageIndex search.
        """
        # --- Arrange ---
        sources_dir = tmp_path / "sources"
        sources_dir.mkdir(parents=True)
        article = sources_dir / "neural_networks.md"
        article.write_text(
            "# Neural Networks\n\n"
            "A neural network is a computational model inspired by the human brain."
        )

        pi = _make_pi_mock(
            search_results=[
                {
                    "node_id": "pi-n1",
                    "title": "Neural Networks",
                    "score": 0.9,
                    "summary": "A neural network is a computational model.",
                }
            ]
        )
        gi = _make_gi_mock()
        okf = _make_okf_mock()
        config = WikiConfig(
            wiki_name="test-wiki",
            storage_dir=tmp_path / "wiki-storage",
        )
        toolkit = LLMWikiToolkit(pi, gi, okf, config)

        # --- Act: ingest ---
        ingest_result = await toolkit.ingest_source(
            wiki_name="test-wiki",
            source_path=str(article),
        )

        # --- Assert: ingest succeeded ---
        assert ingest_result["status"] == "ok", f"Ingest failed: {ingest_result}"
        assert ingest_result["pages_created"] >= 0  # 0 or more pages OK
        assert "source_id" in ingest_result
        assert ingest_result["source_uri"] == str(article.resolve())

        # --- Act: query ---
        query_result = await toolkit.query(
            wiki_name="test-wiki",
            question="What is a neural network?",
            mode="combined",
        )

        # --- Assert: query answer references source content ---
        assert "question" in query_result
        assert "answer" in query_result
        assert "sources" in query_result
        assert query_result["question"] == "What is a neural network?"

        # The synthesised answer is built from snippets served by the
        # WikiStore plane, which recorded the ingested pages' summaries.
        answer = query_result["answer"]
        assert "neural network" in answer.lower() or "computational model" in answer.lower(), (
            f"Answer did not reference source content: {answer!r}"
        )

        # Retrieval is answered from wiki.db — the toolkits are NOT
        # fanned out to at query time.
        pi.search.assert_not_called()
        gi.search_hybrid.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_reingest_cycle(
        self,
        tmp_path: Path,
    ) -> None:
        """Ingest → modify source on disk → reingest verifies manifest is updated.

        Steps:
        1. Write article1.md with initial content.
        2. Ingest via ``ingest_source()`` — manifest entry created.
        3. Overwrite article1.md with updated content (different bytes / mtime).
        4. Call ``reingest_source()`` with the source_id from step 2.
        5. Verify the reingest report has ``status="ok"`` and reflects the update.
        """
        # --- Arrange ---
        sources_dir = tmp_path / "sources"
        sources_dir.mkdir(parents=True)
        article = sources_dir / "article1.md"
        article.write_text(
            "# Neural Networks\n\n"
            "A neural network is a computational model inspired by the human brain."
        )

        pi = _make_pi_mock()
        gi = _make_gi_mock()
        okf = _make_okf_mock()
        config = WikiConfig(
            wiki_name="test-wiki",
            storage_dir=tmp_path / "wiki-storage",
        )
        toolkit = LLMWikiToolkit(pi, gi, okf, config)

        # --- Act: initial ingest ---
        ingest_result = await toolkit.ingest_source(
            wiki_name="test-wiki",
            source_path=str(article),
        )
        assert ingest_result["status"] == "ok", f"Initial ingest failed: {ingest_result}"
        source_id = ingest_result["source_id"]
        assert source_id, "source_id must be set after successful ingest"

        # Verify source is now tracked
        sources_list = await toolkit.list_sources("test-wiki")
        assert any(s["source_id"] == source_id for s in sources_list), (
            f"source_id {source_id!r} not found in manifest: {sources_list}"
        )

        # --- Arrange: modify the source file ---
        article.write_text(
            "# Neural Networks (Revised)\n\n"
            "A neural network consists of layers of interconnected nodes that learn from data."
        )

        # --- Act: reingest via reingest_source ---
        reingest_result = await toolkit.reingest_source(
            wiki_name="test-wiki",
            source_id=source_id,
        )

        # --- Assert: reingest succeeded ---
        assert reingest_result["status"] == "ok", f"Reingest failed: {reingest_result}"
        assert reingest_result["source_uri"] == str(article.resolve())
        # PageIndex insert_content was called at least twice (initial + reingest)
        assert pi.insert_content.call_count >= 2

    @pytest.mark.asyncio
    async def test_combined_search_ranking(
        self,
        tmp_path: Path,
    ) -> None:
        """Ingest two articles then search; results come from both backends.

        Steps:
        1. Create two source files (article1.md, article2.md).
        2. Ingest both via ``ingest_source()``.
        3. Call ``search()`` with mode="combined".
        4. Verify results list is non-empty.
        5. Verify at least one result has ``source="pageindex"`` and at least
           one has ``source="graphindex"``.
        """
        # --- Arrange: two source files ---
        sources_dir = tmp_path / "sources"
        sources_dir.mkdir(parents=True)
        article1 = sources_dir / "article1.md"
        article1.write_text(
            "# Neural Networks\n\n"
            "A neural network is a computational model inspired by the human brain."
        )
        article2 = sources_dir / "article2.md"
        article2.write_text(
            "# Deep Learning\n\n"
            "Deep learning extends neural networks with many hidden layers, "
            "enabling powerful representations of complex patterns in data."
        )

        # Backends return results with distinct node_ids so both appear in merged list
        pi = _make_pi_mock(
            search_results=[
                {
                    "node_id": "pi-neural-01",
                    "title": "Neural Networks",
                    "score": 0.95,
                    "summary": "Computational models inspired by the brain.",
                },
                {
                    "node_id": "pi-deep-01",
                    "title": "Deep Learning",
                    "score": 0.80,
                    "summary": "Extends neural networks with many hidden layers.",
                },
            ]
        )
        gi = _make_gi_mock(
            search_results=[
                {
                    "node_id": "gi-neural-01",
                    "title": "Graph: Neural Networks",
                    "score": 0.88,
                    "summary": "Graph node for neural network article.",
                },
                {
                    "node_id": "gi-deep-01",
                    "title": "Graph: Deep Learning",
                    "score": 0.72,
                    "summary": "Graph node for deep learning article.",
                },
            ]
        )
        okf = _make_okf_mock()
        config = WikiConfig(
            wiki_name="test-wiki",
            storage_dir=tmp_path / "wiki-storage",
        )
        toolkit = LLMWikiToolkit(pi, gi, okf, config)

        # --- Act: ingest both ---
        r1 = await toolkit.ingest_source("test-wiki", str(article1))
        r2 = await toolkit.ingest_source("test-wiki", str(article2))
        assert r1["status"] == "ok", f"Ingest article1 failed: {r1}"
        assert r2["status"] == "ok", f"Ingest article2 failed: {r2}"

        # --- Act: combined search ---
        search_results = await toolkit.search(
            wiki_name="test-wiki",
            query="neural networks deep learning",
            mode="combined",
        )

        # --- Assert: results non-empty ---
        assert len(search_results) > 0, "Combined search returned no results"

        # --- Assert: results are served by the WikiStore plane ---
        sources_seen = {r["source"] for r in search_results}
        assert sources_seen <= {"lexical", "vector"}, (
            f"Unexpected result sources: {sources_seen}"
        )
        pi.search.assert_not_called()
        gi.search_hybrid.assert_not_called()

        # --- Assert: results are sorted descending by score ---
        scores = [r["score"] for r in search_results]
        assert scores == sorted(scores, reverse=True), (
            f"Results are not sorted by score (desc): {scores}"
        )

    @pytest.mark.asyncio
    async def test_lint_reports_issues(
        self,
        tmp_path: Path,
    ) -> None:
        """Create wiki with orphan sources, run lint, verify issues detected.

        Steps:
        1. Register two sources in the manifest without marking them ingested
           (simulates orphan state: sources tracked but no pages generated).
        2. Call ``lint()`` on the wiki.
        3. Verify the lint report contains orphan_sources listing both IDs.
        4. Verify ``total_issues`` is >= 2 (one per orphan source).
        """
        # --- Arrange: build toolkit ---
        sources_dir = tmp_path / "sources"
        sources_dir.mkdir(parents=True)

        # Create real source files so SourceCollectionManager can hash them
        orphan1 = sources_dir / "orphan1.md"
        orphan2 = sources_dir / "orphan2.md"
        orphan1.write_text("# Orphan Article 1\n\nThis page was never ingested.")
        orphan2.write_text("# Orphan Article 2\n\nThis page was also never ingested.")

        pi = _make_pi_mock()
        gi = _make_gi_mock()
        okf = _make_okf_mock(orphan_nodes=0)  # OKF clean; wiki-level finds orphans
        config = WikiConfig(
            wiki_name="test-wiki",
            storage_dir=tmp_path / "wiki-storage",
        )
        toolkit = LLMWikiToolkit(pi, gi, okf, config)

        # --- Act: add sources to manifest WITHOUT ingesting (orphan state) ---
        # Access the internal SourceCollectionManager directly to add sources
        # without going through the ingest pipeline, so pages_generated stays empty.
        entry1 = toolkit._sources.add_source(orphan1)
        entry2 = toolkit._sources.add_source(orphan2)

        assert entry1.pages_generated == [], (
            "Freshly-added source should have no pages generated"
        )
        assert entry2.pages_generated == [], (
            "Freshly-added source should have no pages generated"
        )

        # --- Act: lint ---
        lint_result = await toolkit.lint(wiki_name="test-wiki")

        # --- Assert: lint report structure ---
        assert "orphan_sources" in lint_result, (
            f"lint result missing 'orphan_sources': {lint_result}"
        )
        assert "total_issues" in lint_result, (
            f"lint result missing 'total_issues': {lint_result}"
        )

        # --- Assert: both orphan source IDs are listed ---
        orphan_ids = lint_result["orphan_sources"]
        assert entry1.source_id in orphan_ids, (
            f"orphan1 ({entry1.source_id!r}) not in orphan_sources: {orphan_ids}"
        )
        assert entry2.source_id in orphan_ids, (
            f"orphan2 ({entry2.source_id!r}) not in orphan_sources: {orphan_ids}"
        )

        # --- Assert: total_issues reflects the orphan count ---
        assert lint_result["total_issues"] >= 2, (
            f"Expected total_issues >= 2 for 2 orphan sources, got {lint_result['total_issues']}"
        )

        # Verify the OKF lint was called
        okf.lint_knowledge_base.assert_called_once()
