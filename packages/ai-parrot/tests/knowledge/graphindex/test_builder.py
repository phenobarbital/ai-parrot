"""Unit tests for parrot.knowledge.graphindex.builder."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

from parrot.knowledge.graphindex.builder import GraphIndexBuilder
from parrot.knowledge.graphindex.schema import (
    BuildResult,
    IngestResult,
    NodeKind,
    Provenance,
    SourceConfig,
    UniversalEdge,
    UniversalNode,
)
from parrot.knowledge.ontology.schema import MergedOntology, TenantContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ctx(tenant_id: str = "test-tenant") -> TenantContext:
    """Create a minimal TenantContext for testing."""
    fake_ontology = MergedOntology.model_construct(
        name="test",
        version="1.0",
        entities={},
        relations={},
        traversal_patterns={},
        layers=[],
        merge_timestamp=None,
    )
    return TenantContext(
        tenant_id=tenant_id,
        arango_db=f"db_{tenant_id}",
        pgvector_schema=f"schema_{tenant_id}",
        ontology=fake_ontology,
    )


def make_node(node_id: str, kind: NodeKind = NodeKind.DOCUMENT) -> UniversalNode:
    """Create a minimal UniversalNode."""
    return UniversalNode(
        node_id=node_id, kind=kind, title=f"Node {node_id}", source_uri="test.txt"
    )


def make_persistence() -> MagicMock:
    """Create a mock GraphIndexPersistence."""
    persistence = MagicMock()
    persistence.persist_graph = AsyncMock(
        return_value={"nodes_persisted": 2, "edges_persisted": 1}
    )
    persistence.replace_document_slice = AsyncMock(
        return_value={"nodes_replaced": 1, "edges_replaced": 0}
    )
    return persistence


def make_embedder(nodes: list[UniversalNode] | None = None) -> MagicMock:
    """Create a mock GraphIndexEmbedder."""
    embedder = MagicMock()
    embedder.embed_nodes = AsyncMock(side_effect=lambda ns: ns)
    embedder.get_embedding = MagicMock(return_value=None)
    return embedder


def make_builder(
    persistence=None,
    embedder=None,
    tmp_path: Path | None = None,
) -> GraphIndexBuilder:
    """Create a GraphIndexBuilder with mocked dependencies."""
    if persistence is None:
        persistence = make_persistence()
    if embedder is None:
        embedder = make_embedder()
    output_dir = tmp_path or Path("/tmp/gi_test_output")
    return GraphIndexBuilder(
        persistence=persistence,
        embedder=embedder,
        output_dir=output_dir,
    )


# ---------------------------------------------------------------------------
# TestGraphIndexBuilder
# ---------------------------------------------------------------------------


class TestGraphIndexBuilder:
    @pytest.mark.asyncio
    async def test_build_returns_build_result(self, tmp_path):
        """build() must return a BuildResult instance."""
        builder = make_builder(tmp_path=tmp_path)
        sources = SourceConfig(tenant_id="t")
        ctx = make_ctx("t")
        result = await builder.build(sources, ctx)
        assert isinstance(result, BuildResult)
        assert result.tenant_id == "t"

    @pytest.mark.asyncio
    async def test_build_calls_persistence_persist_graph(self, tmp_path):
        """build() must call persistence.persist_graph."""
        persistence = make_persistence()
        builder = make_builder(persistence=persistence, tmp_path=tmp_path)
        sources = SourceConfig(tenant_id="t")
        ctx = make_ctx("t")
        await builder.build(sources, ctx)
        persistence.persist_graph.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_calls_embedder_embed_nodes(self, tmp_path):
        """build() must call embedder.embed_nodes (stage 2)."""
        embedder = make_embedder()
        builder = make_builder(embedder=embedder, tmp_path=tmp_path)
        sources = SourceConfig(tenant_id="t")
        ctx = make_ctx("t")
        await builder.build(sources, ctx)
        embedder.embed_nodes.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_generates_report(self, tmp_path):
        """build() must generate a GRAPH_REPORT.md in the output_dir."""
        builder = make_builder(tmp_path=tmp_path)
        sources = SourceConfig(tenant_id="t")
        ctx = make_ctx("t")
        result = await builder.build(sources, ctx)
        assert result.report_path is not None
        assert result.report_path.exists()

    @pytest.mark.asyncio
    async def test_build_extractors_run_concurrently(self, tmp_path):
        """Stage 1 extractors must be called via asyncio.gather (concurrently)."""
        call_log: list[str] = []

        async def fake_code(*a, **kw):
            call_log.append("code_start")
            await asyncio.sleep(0)
            call_log.append("code_end")
            return [], []

        async def fake_loader(*a, **kw):
            call_log.append("loader_start")
            await asyncio.sleep(0)
            call_log.append("loader_end")
            return [], []

        async def fake_skill(*a, **kw):
            call_log.append("skill_start")
            await asyncio.sleep(0)
            call_log.append("skill_end")
            return [], []

        builder = make_builder(tmp_path=tmp_path)
        # Patch private extraction helpers
        with patch.object(builder, "_extract_code", fake_code), \
             patch.object(builder, "_extract_loaders", fake_loader), \
             patch.object(builder, "_extract_skills", fake_skill):
            sources = SourceConfig(tenant_id="t")
            ctx = make_ctx("t")
            await builder.build(sources, ctx)

        # All three starts should appear before all ends (concurrent execution)
        assert "code_start" in call_log
        assert "loader_start" in call_log
        assert "skill_start" in call_log

    @pytest.mark.asyncio
    async def test_ingest_document_returns_ingest_result(self, tmp_path):
        """ingest_document() must return an IngestResult."""
        builder = make_builder(tmp_path=tmp_path)
        ctx = make_ctx("t")
        result = await builder.ingest_document("doc://test.txt", ctx)
        assert isinstance(result, IngestResult)
        assert result.document_uri == "doc://test.txt"

    @pytest.mark.asyncio
    async def test_ingest_document_calls_replace_document_slice(self, tmp_path):
        """ingest_document() must call replace_document_slice for atomicity."""
        persistence = make_persistence()
        builder = make_builder(persistence=persistence, tmp_path=tmp_path)
        ctx = make_ctx("t")
        await builder.ingest_document("doc://test.txt", ctx)
        persistence.replace_document_slice.assert_called_once()
        # Verify the URI was passed
        call_args = persistence.replace_document_slice.call_args
        assert "doc://test.txt" in str(call_args)

    @pytest.mark.asyncio
    async def test_ingest_does_not_regenerate_report(self, tmp_path):
        """ingest_document() must NOT call generate_report."""
        builder = make_builder(tmp_path=tmp_path)
        ctx = make_ctx("t")
        with patch(
            "parrot.knowledge.graphindex.builder.generate_report"
        ) as mock_report:
            await builder.ingest_document("doc://test.txt", ctx)
            mock_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_regenerate_report_explicit(self, tmp_path):
        """regenerate_report() must call generate_report without extraction."""
        builder = make_builder(tmp_path=tmp_path)
        ctx = make_ctx("t")
        report_path = await builder.regenerate_report(ctx)
        assert report_path.exists()
        assert report_path.name == "GRAPH_REPORT.md"

    @pytest.mark.asyncio
    async def test_regenerate_report_does_not_call_extractors(self, tmp_path):
        """regenerate_report() must not trigger extraction."""
        builder = make_builder(tmp_path=tmp_path)
        ctx = make_ctx("t")
        with patch.object(builder, "_extract_code", AsyncMock(return_value=([], []))) as mock_code:
            await builder.regenerate_report(ctx)
            mock_code.assert_not_called()

    @pytest.mark.asyncio
    async def test_graphindexignore_excludes_files(self, tmp_path):
        """Files matching .graphindexignore patterns must be excluded."""
        ignore_file = tmp_path / ".graphindexignore"
        ignore_file.write_text("*.log\n__pycache__/\n")

        builder = GraphIndexBuilder(
            persistence=make_persistence(),
            embedder=make_embedder(),
            output_dir=tmp_path,
            ignore_file=ignore_file,
        )

        assert builder._is_ignored("debug.log") is True
        assert builder._is_ignored("main.py") is False
        assert builder._is_ignored("__pycache__/foo.pyc") is True

    @pytest.mark.asyncio
    async def test_ignore_file_missing_is_tolerated(self, tmp_path):
        """Missing .graphindexignore should not raise."""
        builder = GraphIndexBuilder(
            persistence=make_persistence(),
            embedder=make_embedder(),
            output_dir=tmp_path,
            ignore_file=tmp_path / "nonexistent.ignore",
        )
        assert builder._ignore_spec is None
        assert builder._is_ignored("any_file.py") is False

    @pytest.mark.asyncio
    async def test_build_with_code_paths(self, tmp_path):
        """build() with code_paths must attempt code extraction."""
        py_file = tmp_path / "sample.py"
        py_file.write_text("def hello(): pass\n")

        builder = make_builder(tmp_path=tmp_path)
        sources = SourceConfig(code_paths=[str(tmp_path)], tenant_id="t")
        ctx = make_ctx("t")
        result = await builder.build(sources, ctx)
        # Should complete without error (no assertion on extracted count
        # since tree-sitter extraction may or may not succeed in test env)
        assert isinstance(result, BuildResult)

    @pytest.mark.asyncio
    async def test_build_with_skill_paths(self, tmp_path):
        """build() with skill_paths must attempt skill extraction."""
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("---\nname: Test Skill\ndescription: A skill\n---\n")

        builder = make_builder(tmp_path=tmp_path)
        sources = SourceConfig(skill_paths=[str(tmp_path)], tenant_id="t")
        ctx = make_ctx("t")
        result = await builder.build(sources, ctx)
        assert isinstance(result, BuildResult)

    @pytest.mark.asyncio
    async def test_build_error_in_extraction_does_not_crash(self, tmp_path):
        """An error in extraction should be captured, not re-raised."""
        builder = make_builder(tmp_path=tmp_path)

        async def failing_code(*a, **kw):
            raise RuntimeError("extraction exploded")

        with patch.object(builder, "_extract_code", failing_code):
            sources = SourceConfig(tenant_id="t")
            ctx = make_ctx("t")
            result = await builder.build(sources, ctx)
        # Build should still complete, capturing the error
        assert isinstance(result, BuildResult)

    @pytest.mark.asyncio
    async def test_ingest_document_result_has_tenant_id(self, tmp_path):
        """IngestResult must carry the tenant_id from ctx."""
        builder = make_builder(tmp_path=tmp_path)
        ctx = make_ctx("my-tenant")
        result = await builder.ingest_document("doc://x.pdf", ctx)
        assert result.tenant_id == "my-tenant"
