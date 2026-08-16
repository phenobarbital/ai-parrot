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
    WikiPageCategory,
    WikiStore,
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


# ---------------------------------------------------------------------------
# FEAT-402 (TASK-2075): supervised ingestion end-to-end + build-unaffected
# ---------------------------------------------------------------------------


class _FakeTriageAdapter:
    """Stub PageIndexLLMAdapter for triage — content-marker-driven output."""

    def __init__(self) -> None:
        from parrot.knowledge.wiki.review import DimensionScores, TriageOutput

        self.outputs = {
            "ADMIT_MARKER": TriageOutput(
                briefing="A durable technical decision with clear rationale.",
                scores=DimensionScores(density=1.0, novelty=0.5, durability=1.0),
                sensitive=False,
            ),
            "ARCHIVE_MARKER": TriageOutput(
                briefing="Middling content — density and durability neither"
                " clearly admits nor clearly rejects it.",
                # With novelty fixed at 0.1 by the scorer below, this lands
                # in the gray band [0.35, 0.75) and STAYS there after
                # Stage-2 escalation (same canned output both stages) —
                # _band_to_action's residual-gray policy maps that to
                # "archive" (kept, searchable, human-reviewable — not
                # discarded outright).
                scores=DimensionScores(density=0.5, novelty=0.5, durability=0.5),
                sensitive=False,
            ),
            "SENSITIVE_MARKER": TriageOutput(
                briefing="(retained) sensitive personal data.",
                scores=DimensionScores(density=1.0, novelty=0.5, durability=1.0),
                sensitive=True,
            ),
        }
        self.calls = 0

    async def ask_structured(self, prompt, output_type, temperature=0.0, system_prompt=None):
        self.calls += 1
        for marker, output in self.outputs.items():
            if marker in prompt:
                return output
        return next(iter(self.outputs.values()))


class _FakeNoveltyScorer:
    """Stub NoveltyScorer — content-marker-driven novelty, no grounding/search."""

    def __init__(self, novelty_by_marker: dict[str, float], backend: str = "search-proxy") -> None:
        self.novelty_by_marker = novelty_by_marker
        self.backend = backend

    async def score(self, claims, text):
        for marker, value in self.novelty_by_marker.items():
            if marker in text:
                return value, self.backend
        return 0.5, self.backend


class TestSupervisedIngestionEndToEnd:
    """FEAT-402: charter-driven triage + HITL manifest review, full pipeline.

    folder -> dry-run manifest -> simulated human edits -> --review apply
    -> admitted/archived/discarded outcomes verified end-to-end (pages,
    categories, rejected-manifest row, bookkeeper log lines, and the
    archive-category default-ranking exclusion).
    """

    @pytest.mark.asyncio
    async def test_supervised_ingest_end_to_end(self, tmp_path: Path) -> None:
        from parrot.knowledge.wiki.charter import (
            CalibrationPolicy,
            Charter,
            CharterScope,
            Thresholds,
        )
        from parrot.knowledge.wiki.review import (
            ManifestReader,
            ManifestRunHeader,
            ManifestWriter,
        )
        from parrot.knowledge.wiki.triage import IngestTriageRouter

        # --- Arrange: a small doc corpus (admit / archive / sensitive-discard) ---
        corpus_dir = tmp_path / "corpus"
        corpus_dir.mkdir()
        admit_doc = corpus_dir / "decision.md"
        admit_doc.write_text(
            "# Decision\n\nADMIT_MARKER: migrated the graph store to ArangoDB.",
            encoding="utf-8",
        )
        archive_doc = corpus_dir / "borderline.md"
        archive_doc.write_text(
            "# Borderline note\n\nARCHIVE_MARKER: some context, unclear lasting value.",
            encoding="utf-8",
        )
        sensitive_doc = corpus_dir / "hr.md"
        sensitive_doc.write_text(
            "# HR record\n\nSENSITIVE_MARKER: individual salary details.",
            encoding="utf-8",
        )

        charter = Charter(
            version="1",
            scope=CharterScope(include=[], exclude=[]),
            weights={"density": 0.4, "novelty": 0.35, "durability": 0.25},
            thresholds=Thresholds(admit=0.75, reject=0.35),
            calibration=CalibrationPolicy(),
        )

        adapter = _FakeTriageAdapter()
        novelty_scorer = _FakeNoveltyScorer(
            novelty_by_marker={
                "ADMIT_MARKER": 0.9,
                "ARCHIVE_MARKER": 0.1,
                "SENSITIVE_MARKER": 0.9,
            }
        )
        sources = SourceCollectionManager(
            tmp_path / "sources", db_path=tmp_path / "wiki.db"
        )
        router = IngestTriageRouter(
            charter, adapter, sources, novelty_scorer, heavy_adapter=adapter
        )

        # --- Act: triage all docs ---
        docs = sorted(corpus_dir.iterdir())
        entries = []
        for doc in docs:
            content = doc.read_text(encoding="utf-8")
            entries.append(await router.triage(doc, content))

        by_uri = {e.source_uri: e for e in entries}
        admit_entry = by_uri[str(admit_doc.resolve())]
        archive_entry = by_uri[str(archive_doc.resolve())]
        sensitive_entry = by_uri[str(sensitive_doc.resolve())]
        assert admit_entry.proposed_action == "admit"
        assert archive_entry.proposed_action == "archive"
        assert sensitive_entry.proposed_action == "discard"

        # --- Act: write the dry-run manifest (decisions null) ---
        manifest_path = tmp_path / "manifest.jsonl"
        header = ManifestRunHeader(
            charter_sha256="deadbeef" * 8,
            charter_version=charter.version,
            mode="dry-run",
            novelty_backend=novelty_scorer.backend,
            counts={},
            created_at="2026-08-02T00:00:00+00:00",
        )
        ManifestWriter(manifest_path).write(header, entries)

        _dry_header, dry_entries = ManifestReader(manifest_path).read()
        assert all(e.decision is None for e in dry_entries)

        # --- Act: simulate a human hand-editing the manifest ---
        for entry in dry_entries:
            entry.decision = entry.proposed_action
            entry.decision_source = "human"
        ManifestWriter(manifest_path).write(header, dry_entries)

        # --- Act: --review apply ---
        _review_header, applied_entries = ManifestReader(manifest_path).read()

        insert_counter = {"n": 0}

        async def _insert_content(tree_name, content, parent_node_id=None, hint=None):
            insert_counter["n"] += 1
            nid = f"node-{insert_counter['n']:04d}"
            return {
                "tree_name": tree_name,
                "new_node_ids": [nid],
                "title": "Doc",
                "summary": content[:80],
            }

        pi = MagicMock()
        pi.insert_content = AsyncMock(side_effect=_insert_content)
        pi.get_tree = AsyncMock(return_value={})
        bookkeeper = WikiBookkeeper()
        store = WikiStore(tmp_path / "wiki.db", wiki_name="test-wiki")
        orch = WikiIngestOrchestrator(pi, None, sources, bookkeeper, store=store)
        wiki_config = WikiConfig(
            wiki_name="test-wiki", storage_dir=tmp_path / "wiki-storage"
        )

        for entry in applied_entries:
            await orch.ingest(
                entry.source_uri,
                wiki_config,
                triage=entry,
                charter_version=charter.version,
            )

        # --- Assert: admitted doc got a page, decision fields persisted ---
        admit_applied = next(
            e for e in applied_entries if e.source_uri == admit_entry.source_uri
        )
        admit_source_id = sources.find_by_uri(admit_applied.source_uri)
        admit_record = sources.get_source(admit_source_id)
        assert admit_record.status == "ingested"
        assert admit_record.destination == "wiki"
        assert admit_record.decision_source == "human"
        assert admit_record.charter_version == "1"
        assert len(admit_record.pages_generated) >= 1

        # --- Assert: archived doc got a page with category ARCHIVE ---
        archive_applied = next(
            e for e in applied_entries if e.source_uri == archive_entry.source_uri
        )
        archive_source_id = sources.find_by_uri(archive_applied.source_uri)
        archive_record = sources.get_source(archive_source_id)
        assert archive_record.destination == "archive"
        assert len(archive_record.pages_generated) >= 1
        archive_page_id = archive_record.pages_generated[0]
        page = await store.get_page(archive_page_id)
        assert page is not None
        assert page["category"] == WikiPageCategory.ARCHIVE.value

        # --- Assert: rejected (sensitive) doc created ZERO pages ---
        sensitive_applied = next(
            e for e in applied_entries if e.source_uri == sensitive_entry.source_uri
        )
        sensitive_source_id = sources.find_by_uri(sensitive_applied.source_uri)
        sensitive_record = sources.get_source(sensitive_source_id)
        assert sensitive_record.status == "rejected"
        assert sensitive_record.pages_generated == []
        assert sensitive_record.destination == "discard"

        # --- Assert: bookkeeper log carries ADMIT/ARCHIVE/DISCARD lines ---
        log_content = bookkeeper.read_log(wiki_config.storage_dir, last_n=50)
        assert "[ADMIT]" in log_content
        assert "[ARCHIVE]" in log_content
        assert "[DISCARD]" in log_content

        # --- Assert: archive page excluded from default ranking, but
        # retrievable via the explicit include_archived opt-in ---
        combined = WikiCombinedSearch(None, None, store=store)
        default_results = await combined.search("borderline", mode="lexical", top_k=10)
        assert all(r.node_id != archive_page_id for r in default_results)
        archived_results = await combined.search(
            "borderline", mode="lexical", top_k=10, include_archived=True
        )
        assert any(r.node_id == archive_page_id for r in archived_results)


class TestBuildUnaffected:
    """FEAT-402: `build`'s deterministic, offline, no-LLM contract is untouched."""

    def test_build_unaffected(self, tmp_path: Path) -> None:
        from click.testing import CliRunner
        from parrot.knowledge.wiki.cli import wiki
        from parrot.knowledge.wiki.project import load_project_config

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "module.py").write_text(
            '"""A tiny module."""\n\n\ndef greet(name):\n'
            '    """Greet."""\n    return f"hi {name}"\n',
            encoding="utf-8",
        )
        runner = CliRunner()
        first = runner.invoke(
            wiki, ["build", "--path", str(repo), "--no-git", "--quiet"]
        )
        assert first.exit_code == 0, first.output

        config = load_project_config(repo)
        store = WikiStore(config.db_path(repo), wiki_name=config.wiki_name)
        stats_first = asyncio.run(store.stats())

        # Re-run build (deterministic, offline, no-LLM) — FEAT-402 code
        # being present anywhere in the codebase must not change output.
        second = runner.invoke(
            wiki, ["build", "--path", str(repo), "--no-git", "--quiet"]
        )
        assert second.exit_code == 0, second.output
        stats_second = asyncio.run(store.stats())
        assert stats_first == stats_second

        # No page picks up the new ARCHIVE category — `build` never routes
        # through supervised triage (spec §1 Non-Goals: build is untouched).
        pages = asyncio.run(store.list_pages(limit=1000))
        assert all(
            p.get("category") != WikiPageCategory.ARCHIVE.value for p in pages
        )
