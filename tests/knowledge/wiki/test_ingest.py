"""Unit tests for WikiIngestOrchestrator and IngestReport (TASK-1632)."""

import builtins
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.ingest import IngestReport, WikiIngestOrchestrator
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.sources import SourceCollectionManager

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def wiki_config(tmp_path: Path) -> WikiConfig:
    """Minimal WikiConfig pointing to tmp_path."""
    return WikiConfig(wiki_name="test-wiki", storage_dir=tmp_path)


@pytest.fixture
def sample_source(tmp_path: Path) -> Path:
    """Create a sample markdown source file."""
    f = tmp_path / "article.md"
    f.write_text("# Neural Networks\n\nA neural network is a computational model.")
    return f


@pytest.fixture
def mock_pi():
    """Mock PageIndexToolkit."""
    pi = MagicMock()
    # Real PageIndexToolkit.insert_content contract (FEAT-238):
    # {"tree_name", "new_node_ids", "title", "summary"}
    pi.insert_content = AsyncMock(
        return_value={
            "tree_name": "test-wiki",
            "new_node_ids": ["0001", "0002", "0003"],
            "title": "Neural Networks",
            "summary": "A neural network is a computational model.",
        }
    )
    pi.create_tree = AsyncMock(return_value={"tree_name": "test-wiki"})
    return pi


@pytest.fixture
def mock_gi():
    """Mock GraphIndexToolkit."""
    gi = MagicMock()
    gi.create_node = AsyncMock(return_value={"node_id": "wp-001", "status": "created"})
    gi.link_nodes = AsyncMock(return_value={"status": "ok"})
    return gi


@pytest.fixture
def source_manager(tmp_path: Path) -> SourceCollectionManager:
    """Real SourceCollectionManager backed by tmp_path."""
    return SourceCollectionManager(tmp_path / "sources")


@pytest.fixture
def bookkeeper() -> WikiBookkeeper:
    """Real WikiBookkeeper (stateless)."""
    return WikiBookkeeper()


@pytest.fixture
def orchestrator(mock_pi, mock_gi, source_manager, bookkeeper) -> WikiIngestOrchestrator:
    """Fully wired orchestrator with mocked toolkits."""
    return WikiIngestOrchestrator(mock_pi, mock_gi, source_manager, bookkeeper)


# ---------------------------------------------------------------------------
# IngestReport model tests
# ---------------------------------------------------------------------------

class TestIngestReport:
    """Tests for the IngestReport Pydantic model."""

    def test_defaults(self):
        """IngestReport defaults are zero / 'ok'."""
        report = IngestReport(source_id="s1", source_uri="/doc.md")
        assert report.pages_created == 0
        assert report.pages_updated == 0
        assert report.graph_nodes_created == 0
        assert report.status == "ok"
        assert report.error is None

    def test_serialisation(self):
        """model_dump round-trips cleanly."""
        report = IngestReport(
            source_id="s1",
            source_uri="/doc.md",
            pages_created=3,
            status="ok",
        )
        data = report.model_dump()
        assert data["pages_created"] == 3
        assert data["status"] == "ok"

    def test_negative_pages_rejected(self):
        """pages_created must be >= 0."""
        with pytest.raises(Exception):
            IngestReport(source_id="x", source_uri="/doc", pages_created=-1)


# ---------------------------------------------------------------------------
# WikiIngestOrchestrator tests
# ---------------------------------------------------------------------------

class TestWikiIngestOrchestrator:
    """Tests for WikiIngestOrchestrator."""

    @pytest.mark.asyncio
    async def test_ingest_returns_report(
        self,
        orchestrator: WikiIngestOrchestrator,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """ingest() returns an IngestReport instance."""
        report = await orchestrator.ingest(str(sample_source), wiki_config)
        assert isinstance(report, IngestReport)

    @pytest.mark.asyncio
    async def test_ingest_status_ok(
        self,
        orchestrator: WikiIngestOrchestrator,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """Successful ingest produces status='ok'."""
        report = await orchestrator.ingest(str(sample_source), wiki_config)
        assert report.status == "ok"

    @pytest.mark.asyncio
    async def test_ingest_records_generated_page_ids(
        self,
        orchestrator: WikiIngestOrchestrator,
        source_manager: SourceCollectionManager,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """Regression (G1): the real insert_content contract returns
        ``new_node_ids`` — ingest must count them as pages_created and
        record them in the manifest so sources do not lint as orphans."""
        report = await orchestrator.ingest(str(sample_source), wiki_config)
        assert report.pages_created == 3
        entry = source_manager.get_source(report.source_id)
        assert entry is not None
        # PageIndex node ids MUST be present (graph node id may be appended)
        assert {"0001", "0002", "0003"}.issubset(set(entry.pages_generated))

    @pytest.mark.asyncio
    async def test_ingest_calls_insert_content(
        self,
        orchestrator: WikiIngestOrchestrator,
        mock_pi,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """insert_content is called with the correct tree_name."""
        await orchestrator.ingest(str(sample_source), wiki_config)
        mock_pi.insert_content.assert_called_once()
        call_args = mock_pi.insert_content.call_args
        assert call_args[0][0] == "test-wiki"  # tree_name

    @pytest.mark.asyncio
    async def test_ingest_creates_graph_node(
        self,
        mock_pi,
        mock_gi,
        source_manager: SourceCollectionManager,
        bookkeeper: WikiBookkeeper,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """With sync_graph=True, create_node is called on GraphIndexToolkit."""
        orchestrator = WikiIngestOrchestrator(
            mock_pi, mock_gi, source_manager, bookkeeper, sync_graph=True
        )
        await orchestrator.ingest(str(sample_source), wiki_config)
        mock_gi.create_node.assert_called_once()
        call_kwargs = mock_gi.create_node.call_args[1] if mock_gi.create_node.call_args[1] else {}
        call_args = mock_gi.create_node.call_args[0] if mock_gi.create_node.call_args[0] else ()
        # Verify kind="wiki_page" was passed
        all_args = {**{str(i): v for i, v in enumerate(call_args)}, **call_kwargs}
        assert "wiki_page" in str(all_args)

    @pytest.mark.asyncio
    async def test_ingest_graph_nodes_created(
        self,
        mock_pi,
        mock_gi,
        source_manager: SourceCollectionManager,
        bookkeeper: WikiBookkeeper,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """graph_nodes_created >= 1 when sync_graph=True."""
        orchestrator = WikiIngestOrchestrator(
            mock_pi, mock_gi, source_manager, bookkeeper, sync_graph=True
        )
        report = await orchestrator.ingest(str(sample_source), wiki_config)
        assert report.graph_nodes_created >= 1

    @pytest.mark.asyncio
    async def test_ingest_graph_sync_off_by_default(
        self,
        orchestrator: WikiIngestOrchestrator,
        mock_gi,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """GraphIndex is NOT touched by default — WikiStore is the plane."""
        report = await orchestrator.ingest(str(sample_source), wiki_config)
        assert report.status == "ok"
        assert report.graph_nodes_created == 0
        mock_gi.create_node.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_updates_manifest(
        self,
        orchestrator: WikiIngestOrchestrator,
        source_manager: SourceCollectionManager,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """Source manifest contains the ingested source after ingest."""
        await orchestrator.ingest(str(sample_source), wiki_config)
        sources = source_manager.list_sources()
        assert len(sources) >= 1
        uris = [s.source_uri for s in sources]
        assert str(sample_source.resolve()) in uris

    @pytest.mark.asyncio
    async def test_ingest_writes_log(
        self,
        orchestrator: WikiIngestOrchestrator,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """log.md is created with an INGEST entry after ingest."""
        await orchestrator.ingest(str(sample_source), wiki_config)
        log_path = wiki_config.storage_dir / "log.md"
        assert log_path.exists()
        content = log_path.read_text()
        assert "[INGEST]" in content

    @pytest.mark.asyncio
    async def test_ingest_missing_file_returns_error(
        self,
        orchestrator: WikiIngestOrchestrator,
        wiki_config: WikiConfig,
        tmp_path: Path,
    ):
        """ingest() returns status='error' when the source file does not exist."""
        missing = str(tmp_path / "ghost.md")
        # SourceCollectionManager.add_source raises FileNotFoundError;
        # ingest must catch it and return an error report.
        report = await orchestrator.ingest(missing, wiki_config)
        assert report.status == "error"
        assert report.error is not None

    @pytest.mark.asyncio
    async def test_ingest_skips_fresh_source(
        self,
        orchestrator: WikiIngestOrchestrator,
        mock_pi,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """Re-ingesting an unchanged source is skipped (insert_content not called twice)."""
        await orchestrator.ingest(str(sample_source), wiki_config)
        first_call_count = mock_pi.insert_content.call_count

        # Ingest again without modifying the file
        report = await orchestrator.ingest(str(sample_source), wiki_config)
        assert report.status == "ok"
        # insert_content should NOT be called again
        assert mock_pi.insert_content.call_count == first_call_count

    @pytest.mark.asyncio
    async def test_ingest_graph_failure_non_fatal(
        self,
        tmp_path: Path,
        wiki_config: WikiConfig,
        sample_source: Path,
        source_manager: SourceCollectionManager,
        bookkeeper: WikiBookkeeper,
    ):
        """GraphIndex failure is logged but ingest still succeeds."""
        pi = MagicMock()
        pi.insert_content = AsyncMock(
            return_value={"tree_name": "test-wiki", "new_node_ids": ["0001", "0002"]}
        )
        gi = MagicMock()
        gi.create_node = AsyncMock(side_effect=RuntimeError("GI down"))

        orch = WikiIngestOrchestrator(
            pi, gi, source_manager, bookkeeper, sync_graph=True
        )
        report = await orch.ingest(str(sample_source), wiki_config)
        assert report.status == "ok"
        assert report.graph_nodes_created == 0  # failed, but not fatal

    @pytest.mark.asyncio
    async def test_ingest_duration_populated(
        self,
        orchestrator: WikiIngestOrchestrator,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """duration_ms is a positive float after ingest."""
        report = await orchestrator.ingest(str(sample_source), wiki_config)
        assert report.duration_ms >= 0.0


class TestIngestWikiStoreSync:
    """Ingest writes pages + provenance edges into the WikiStore plane."""

    @pytest.fixture
    def store(self, tmp_path: Path):
        from parrot.knowledge.wiki.store import WikiStore

        return WikiStore(tmp_path / "wiki.db", wiki_name="test-wiki")

    @pytest.fixture
    def store_orchestrator(
        self, mock_pi, mock_gi, source_manager, bookkeeper, store
    ) -> WikiIngestOrchestrator:
        return WikiIngestOrchestrator(
            mock_pi, mock_gi, source_manager, bookkeeper, store=store
        )

    @pytest.mark.asyncio
    async def test_ingest_upserts_pages_into_store(
        self,
        store_orchestrator: WikiIngestOrchestrator,
        store,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        report = await store_orchestrator.ingest(str(sample_source), wiki_config)
        assert report.status == "ok"
        stats = await store.stats()
        assert stats["pages"] == 3  # one per new_node_id from the mock

    @pytest.mark.asyncio
    async def test_ingest_records_summarizes_edges(
        self,
        store_orchestrator: WikiIngestOrchestrator,
        store,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        report = await store_orchestrator.ingest(str(sample_source), wiki_config)
        page = await store.get_page("0001")
        assert page is not None
        out = await store.neighbors("0001", rel="summarizes", direction="out")
        assert len(out) == 1
        assert out[0]["concept_id"] == report.source_id

    @pytest.mark.asyncio
    async def test_reingest_does_not_duplicate_pages(
        self,
        store_orchestrator: WikiIngestOrchestrator,
        store,
        source_manager: SourceCollectionManager,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """G9 regression: re-ingest replaces the source slice atomically."""
        report = await store_orchestrator.ingest(str(sample_source), wiki_config)
        # Force staleness so the second ingest is not skipped
        sample_source.write_text(sample_source.read_text() + "\nMore.")
        report2 = await store_orchestrator.ingest(str(sample_source), wiki_config)
        assert report2.status == "ok"
        assert report.source_id == report2.source_id
        stats = await store.stats()
        assert stats["pages"] == 3  # replaced, not accumulated


def _make_triage_entry(
    *,
    proposed_action="admit",
    decision=None,
    briefing="A concise triage briefing.",
    composite=0.8,
    decision_source="model",
):
    """Build a minimal ManifestDocEntry for orchestrator wiring tests."""
    from parrot.knowledge.wiki.review import DimensionScores, ManifestDocEntry

    return ManifestDocEntry(
        source_uri="/docs/article.md",
        file_hash="a" * 40,
        briefing=briefing,
        scores=DimensionScores(density=0.7, novelty=0.7, durability=0.7),
        composite=composite,
        proposed_action=proposed_action,
        decision=decision,
        decision_source=decision_source,
    )


class TestOrchestratorTriageWiring:
    """FEAT-402 (TASK-2074): orchestrator triage context wiring."""

    @pytest.mark.asyncio
    async def test_orchestrator_forwards_hint(
        self,
        orchestrator: WikiIngestOrchestrator,
        mock_pi,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """The triage briefing reaches insert_content(hint=...)."""
        triage = _make_triage_entry(briefing="Decided to migrate to ArangoDB.")
        await orchestrator.ingest(str(sample_source), wiki_config, triage=triage)

        mock_pi.insert_content.assert_called_once()
        call_kwargs = mock_pi.insert_content.call_args.kwargs
        assert call_kwargs.get("hint") == "Decided to migrate to ArangoDB."

    @pytest.mark.asyncio
    async def test_orchestrator_no_triage_hint_is_none(
        self,
        orchestrator: WikiIngestOrchestrator,
        mock_pi,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """Legacy path (triage=None): hint is explicitly None."""
        await orchestrator.ingest(str(sample_source), wiki_config)
        call_kwargs = mock_pi.insert_content.call_args.kwargs
        assert call_kwargs.get("hint") is None

    @pytest.mark.asyncio
    async def test_orchestrator_archive_category(
        self,
        mock_pi,
        mock_gi,
        source_manager: SourceCollectionManager,
        bookkeeper: WikiBookkeeper,
        sample_source: Path,
        wiki_config: WikiConfig,
        tmp_path: Path,
    ):
        """Archive-destination docs produce pages with category 'archive'."""
        from parrot.knowledge.wiki.store import WikiStore

        store = WikiStore(tmp_path / "wiki.db", wiki_name="test-wiki")
        orch = WikiIngestOrchestrator(
            mock_pi, mock_gi, source_manager, bookkeeper, store=store
        )
        triage = _make_triage_entry(proposed_action="archive")

        report = await orch.ingest(str(sample_source), wiki_config, triage=triage)
        assert report.status == "ok"
        assert report.pages_created == 3

        page = await store.get_page("0001")
        assert page is not None
        assert page["category"] == "archive"

    @pytest.mark.asyncio
    async def test_orchestrator_reject_no_pages(
        self,
        orchestrator: WikiIngestOrchestrator,
        mock_pi,
        source_manager: SourceCollectionManager,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """Discard-destination docs create ZERO pages and a rejected manifest row."""
        triage = _make_triage_entry(proposed_action="discard", decision_source="heuristic")

        report = await orchestrator.ingest(str(sample_source), wiki_config, triage=triage)

        assert report.status == "ok"
        assert report.pages_created == 0
        mock_pi.insert_content.assert_not_called()

        entry = source_manager.get_source(report.source_id)
        assert entry is not None
        assert entry.status == "rejected"
        assert entry.pages_generated == []
        assert entry.destination == "discard"

    @pytest.mark.asyncio
    async def test_orchestrator_reject_writes_discard_log(
        self,
        orchestrator: WikiIngestOrchestrator,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """A DISCARD line is written to log.md."""
        triage = _make_triage_entry(proposed_action="discard")
        await orchestrator.ingest(str(sample_source), wiki_config, triage=triage)

        log_path = wiki_config.storage_dir / "log.md"
        assert log_path.exists()
        assert "[DISCARD]" in log_path.read_text()

    @pytest.mark.asyncio
    async def test_orchestrator_admit_writes_admit_log_and_decision_fields(
        self,
        orchestrator: WikiIngestOrchestrator,
        source_manager: SourceCollectionManager,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """Admitted docs log ADMIT and persist decision fields via record_decision."""
        triage = _make_triage_entry(
            proposed_action="admit", decision_source="model", composite=0.91
        )
        report = await orchestrator.ingest(
            str(sample_source), wiki_config, triage=triage, charter_version="3"
        )
        assert report.status == "ok"

        log_path = wiki_config.storage_dir / "log.md"
        assert "[ADMIT]" in log_path.read_text()

        entry = source_manager.get_source(report.source_id)
        assert entry is not None
        assert entry.destination == "wiki"
        assert entry.decision_source == "model"
        assert entry.charter_version == "3"
        assert entry.composite_score == pytest.approx(0.91)

    @pytest.mark.asyncio
    async def test_orchestrator_archive_writes_archive_log(
        self,
        orchestrator: WikiIngestOrchestrator,
        source_manager: SourceCollectionManager,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """Archived docs log ARCHIVE and persist destination='archive'."""
        triage = _make_triage_entry(proposed_action="archive")
        report = await orchestrator.ingest(str(sample_source), wiki_config, triage=triage)

        log_path = wiki_config.storage_dir / "log.md"
        assert "[ARCHIVE]" in log_path.read_text()

        entry = source_manager.get_source(report.source_id)
        assert entry is not None
        assert entry.destination == "archive"

    @pytest.mark.asyncio
    async def test_orchestrator_reapply_idempotent(
        self,
        mock_pi,
        mock_gi,
        source_manager: SourceCollectionManager,
        bookkeeper: WikiBookkeeper,
        sample_source: Path,
        wiki_config: WikiConfig,
        tmp_path: Path,
    ):
        """Re-applying the same source (unchanged content) replaces pages,
        never duplicates — and re-persists the (possibly edited) decision."""
        from parrot.knowledge.wiki.store import WikiStore

        store = WikiStore(tmp_path / "wiki.db", wiki_name="test-wiki")
        orch = WikiIngestOrchestrator(
            mock_pi, mock_gi, source_manager, bookkeeper, store=store
        )
        triage = _make_triage_entry(proposed_action="admit", decision_source="human")

        report1 = await orch.ingest(str(sample_source), wiki_config, triage=triage)
        # Re-apply WITHOUT changing the file content — the legacy
        # staleness skip must NOT short-circuit a triage-driven re-apply.
        report2 = await orch.ingest(str(sample_source), wiki_config, triage=triage)

        assert report1.status == report2.status == "ok"
        assert report1.source_id == report2.source_id
        assert mock_pi.insert_content.call_count == 2  # not skipped

        stats = await store.stats()
        assert stats["pages"] == 3  # replaced, not accumulated

    @pytest.mark.asyncio
    async def test_orchestrator_decision_takes_precedence_over_proposed_action(
        self,
        orchestrator: WikiIngestOrchestrator,
        source_manager: SourceCollectionManager,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """A human-edited `decision` overrides the router's `proposed_action`."""
        triage = _make_triage_entry(proposed_action="admit", decision="discard")

        report = await orchestrator.ingest(str(sample_source), wiki_config, triage=triage)

        assert report.pages_created == 0
        entry = source_manager.get_source(report.source_id)
        assert entry is not None
        assert entry.status == "rejected"


@pytest.fixture
def no_parrot_loaders(monkeypatch):
    """Force `from parrot_loaders... import ...` to raise ImportError."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("parrot_loaders"):
            raise ImportError("simulated: ai-parrot-loaders not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


class TestFrontmatterWiring:
    """FEAT-451 (TASK-2356): page frontmatter + document metadata wiring."""

    @pytest.fixture
    def store(self, tmp_path: Path):
        from parrot.knowledge.wiki.store import WikiStore

        return WikiStore(tmp_path / "wiki-frontmatter.db", wiki_name="test-wiki")

    @pytest.fixture
    def store_orchestrator(
        self, mock_pi, mock_gi, source_manager, bookkeeper, store
    ) -> WikiIngestOrchestrator:
        return WikiIngestOrchestrator(
            mock_pi, mock_gi, source_manager, bookkeeper, store=store
        )

    @staticmethod
    async def _page_bodies(store, node_ids):
        bodies = []
        for nid in node_ids:
            page = await store.get_page(nid)
            assert page is not None
            bodies.append(page["body"])
        return bodies

    @pytest.mark.asyncio
    async def test_pages_carry_frontmatter(
        self, store_orchestrator, store, sample_source, wiki_config
    ):
        """Also exercises the fallback (``node is None``) branch: ``mock_pi``
        has no ``get_tree`` configured, so ``_build_page_records`` can never
        resolve a node and every record goes through that branch."""
        triage = _make_triage_entry(
            proposed_action="admit", decision_source="model", composite=0.8
        )
        report = await store_orchestrator.ingest(
            str(sample_source), wiki_config, triage=triage, charter_version="1.2.0"
        )
        assert report.status == "ok"

        page = await store.get_page("0001")
        assert page is not None
        body = page["body"]
        assert body.startswith("---\n")
        block = body.split("---\n", 2)[1]
        parsed = yaml.safe_load(block)
        assert parsed["triage"]["charter_version"] == "1.2.0"
        assert parsed["triage"]["composite_score"] == pytest.approx(triage.composite)
        assert parsed["triage"]["decision"] == (
            triage.decision or triage.proposed_action
        )

    @pytest.mark.asyncio
    async def test_all_pages_identical_frontmatter(
        self, store_orchestrator, store, sample_source, wiki_config
    ):
        triage = _make_triage_entry(proposed_action="admit")
        await store_orchestrator.ingest(
            str(sample_source), wiki_config, triage=triage, charter_version="1"
        )
        bodies = await self._page_bodies(store, ["0001", "0002", "0003"])
        blocks = [b.split("---\n", 2)[1] for b in bodies]
        assert len(set(blocks)) == 1

    @pytest.mark.asyncio
    async def test_fallback_branch_gets_frontmatter(self, orchestrator):
        """``node is None`` branch (unresolvable tree/node) must be
        prefixed with frontmatter — checked directly against
        ``_build_page_records`` so it cannot be confused with the
        resolved-node branch below."""
        records = await orchestrator._build_page_records(
            "test-wiki",
            ["n1"],
            source_id="src-1",
            fallback_title="FT",
            fallback_summary="FS",
            frontmatter="---\ntitle: X\n---\n\n",
        )
        assert len(records) == 1
        assert records[0].body.startswith("---\ntitle: X\n---\n\n")

    @pytest.mark.asyncio
    async def test_resolved_node_branch_gets_frontmatter(self, orchestrator, mock_pi):
        """The resolved-node branch (a real tree/node found) must ALSO be
        prefixed — the fallback branch is not the only construction site."""
        mock_pi.get_tree = AsyncMock(
            return_value={
                "structure": {
                    "node_id": "root",
                    "child_nodes": [
                        {
                            "node_id": "0001",
                            "concept_id": "c-0001",
                            "title": "T",
                            "summary": "S",
                            "category": "concept",
                        }
                    ],
                }
            }
        )
        records = await orchestrator._build_page_records(
            "test-wiki",
            ["0001"],
            source_id="src-1",
            fallback_title="FT",
            fallback_summary="FS",
            frontmatter="---\ntitle: X\n---\n\n",
        )
        assert len(records) == 1
        assert records[0].body.startswith("---\ntitle: X\n---\n\n")

    @pytest.mark.asyncio
    async def test_token_count_includes_frontmatter(
        self, store_orchestrator, store, sample_source, wiki_config
    ):
        from parrot.knowledge.wiki.store import estimate_tokens

        triage = _make_triage_entry(proposed_action="admit")
        await store_orchestrator.ingest(
            str(sample_source), wiki_config, triage=triage, charter_version="1"
        )
        page = await store.get_page("0001")
        assert page is not None
        assert page["token_count"] == estimate_tokens(page["body"])

    @pytest.mark.asyncio
    async def test_legacy_path_emits_no_frontmatter(
        self, store_orchestrator, store, sample_source, wiki_config
    ):
        """``triage=None`` -> build/upsert path -> byte-identical, no frontmatter."""
        report = await store_orchestrator.ingest(str(sample_source), wiki_config)
        assert report.status == "ok"
        page = await store.get_page("0001")
        assert page is not None
        assert not page["body"].startswith("---\n")

    @pytest.mark.asyncio
    async def test_metadata_persisted(
        self,
        orchestrator: WikiIngestOrchestrator,
        source_manager: SourceCollectionManager,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        triage = _make_triage_entry(proposed_action="admit")
        report = await orchestrator.ingest(
            str(sample_source), wiki_config, triage=triage, charter_version="1.2.0"
        )
        entry = source_manager.get_source(report.source_id)
        assert entry is not None
        assert entry.doc_metadata is not None
        assert entry.content_type is not None
        assert entry.loader == "plaintext"

    @pytest.mark.asyncio
    async def test_acquisition_error_propagates(
        self,
        orchestrator: WikiIngestOrchestrator,
        wiki_config: WikiConfig,
        tmp_path: Path,
        no_parrot_loaders,
    ):
        from parrot.knowledge.wiki.documents import DocumentAcquisitionError

        p = tmp_path / "undecodable.pdf"
        p.write_bytes(b"%PDF-1.4\n\x00\x01binary")
        with pytest.raises(DocumentAcquisitionError):
            await orchestrator.ingest(str(p), wiki_config)

    @pytest.mark.asyncio
    async def test_discard_creates_nothing(
        self,
        orchestrator: WikiIngestOrchestrator,
        mock_pi,
        source_manager: SourceCollectionManager,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """The discard path pre-dates this task and is untouched: no
        acquisition, no frontmatter, no doc_metadata persisted."""
        triage = _make_triage_entry(proposed_action="discard")
        report = await orchestrator.ingest(
            str(sample_source), wiki_config, triage=triage
        )
        assert report.pages_created == 0
        mock_pi.insert_content.assert_not_called()

        entry = source_manager.get_source(report.source_id)
        assert entry is not None
        assert entry.status == "rejected"
        assert entry.doc_metadata is None

    @pytest.mark.asyncio
    async def test_acquired_reused_not_reacquired(
        self,
        orchestrator: WikiIngestOrchestrator,
        sample_source: Path,
        wiki_config: WikiConfig,
        monkeypatch,
    ):
        """``ingest(acquired=...)`` must not re-acquire through
        DocumentAcquirer — the whole point is to keep the triaged and
        ingested text in agreement without a second extraction pass."""
        import parrot.knowledge.wiki.ingest as ingest_module
        from parrot.knowledge.wiki.documents import (
            AcquiredDocument,
            DocumentMetadata,
            DocumentRef,
        )

        called = {"count": 0}

        class _BoomAcquirer:
            async def acquire(self, ref):
                called["count"] += 1
                raise AssertionError(
                    "should not re-acquire when `acquired` is given"
                )

        monkeypatch.setattr(ingest_module, "DocumentAcquirer", _BoomAcquirer)

        pre_acquired = AcquiredDocument(
            ref=DocumentRef(uri=str(sample_source), suffix=".md"),
            text=sample_source.read_text(),
            metadata=DocumentMetadata(loader="plaintext"),
        )
        triage = _make_triage_entry(proposed_action="admit")
        report = await orchestrator.ingest(
            str(sample_source),
            wiki_config,
            triage=triage,
            acquired=pre_acquired,
        )
        assert report.status == "ok"
        assert called["count"] == 0
