"""Unit tests for WikiIngestOrchestrator and IngestReport (TASK-1632)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator, IngestReport
from parrot.knowledge.wiki.models import WikiConfig
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper


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
        orchestrator: WikiIngestOrchestrator,
        mock_gi,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """create_node is called on GraphIndexToolkit."""
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
        orchestrator: WikiIngestOrchestrator,
        sample_source: Path,
        wiki_config: WikiConfig,
    ):
        """graph_nodes_created >= 1 after successful ingest."""
        report = await orchestrator.ingest(str(sample_source), wiki_config)
        assert report.graph_nodes_created >= 1

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

        orch = WikiIngestOrchestrator(pi, gi, source_manager, bookkeeper)
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
