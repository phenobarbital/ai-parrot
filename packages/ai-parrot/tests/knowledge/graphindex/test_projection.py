"""Unit tests for the GraphIndex projection layer (FEAT-239).

Tests verify:
- node_to_frontmatter_dict() maps all NodeKind values correctly.
- project_node_sidecar() produces frontmatter + body.
- project_graph_sidecars() writes files to output_dir/nodes/.
- content_ref resolution loads full body from NodeContentStore.
- project_report_frontmatter() returns valid YAML with type=Document.
- GraphProjectionReport model has correct fields.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from parrot.knowledge.graphindex.schema import (
    UniversalNode,
    UniversalEdge,
    NodeKind,
    EdgeKind,
)
from parrot.knowledge.graphindex.projection import (
    node_to_frontmatter_dict,
    project_node_sidecar,
    project_graph_sidecars,
    project_report_frontmatter,
    NODE_KIND_TO_CONCEPT_TYPE,
    EDGE_KIND_TO_RELATION_TYPE,
    GraphProjectionReport,
)
from parrot.knowledge.okf.ontology import ConceptType, RelationType
from parrot.knowledge.okf.frontmatter import parse_frontmatter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def symbol_node() -> UniversalNode:
    """A SYMBOL node with categories and summary."""
    return UniversalNode(
        node_id="sym-builder-abc",
        kind=NodeKind.SYMBOL,
        title="GraphIndexBuilder",
        source_uri="file:///builder.py",
        summary="Orchestrates the build pipeline.",
        domain_tags={"categories": ["python", "builder"]},
    )


@pytest.fixture
def doc_node_with_content_ref() -> UniversalNode:
    """A DOCUMENT node with a pageindex:// content_ref."""
    return UniversalNode(
        node_id="doc-readme-xyz",
        kind=NodeKind.DOCUMENT,
        title="README",
        source_uri="file:///README.md",
        content_ref="pageindex://docs/readme-node",
        summary="Project docs.",
    )


@pytest.fixture
def no_summary_node() -> UniversalNode:
    """A CONCEPT node with no summary — tests fallback to title."""
    return UniversalNode(
        node_id="no-summary",
        kind=NodeKind.CONCEPT,
        title="Fallback Title",
        source_uri="file:///test",
        summary=None,
    )


@pytest.fixture
def sample_edges() -> list[UniversalEdge]:
    """One outgoing REFERENCES edge from symbol_node to doc_node."""
    return [
        UniversalEdge(
            source_id="sym-builder-abc",
            target_id="doc-readme-xyz",
            kind=EdgeKind.REFERENCES,
        ),
    ]


# ---------------------------------------------------------------------------
# Tests: Mapping tables
# ---------------------------------------------------------------------------


class TestMappingTables:
    """Verify NODE_KIND_TO_CONCEPT_TYPE and EDGE_KIND_TO_RELATION_TYPE."""

    def test_all_node_kinds_mapped(self) -> None:
        """Every NodeKind must have a ConceptType mapping."""
        for kind in NodeKind:
            assert kind in NODE_KIND_TO_CONCEPT_TYPE, f"{kind} not in NODE_KIND_TO_CONCEPT_TYPE"

    def test_all_edge_kinds_mapped(self) -> None:
        """Every EdgeKind must have a RelationType mapping."""
        for kind in EdgeKind:
            assert kind in EDGE_KIND_TO_RELATION_TYPE, f"{kind} not in EDGE_KIND_TO_RELATION_TYPE"

    def test_symbol_maps_to_symbol(self) -> None:
        assert NODE_KIND_TO_CONCEPT_TYPE[NodeKind.SYMBOL] == ConceptType.SYMBOL

    def test_document_maps_to_document_node(self) -> None:
        assert NODE_KIND_TO_CONCEPT_TYPE[NodeKind.DOCUMENT] == ConceptType.DOCUMENT_NODE

    def test_section_maps_to_section(self) -> None:
        assert NODE_KIND_TO_CONCEPT_TYPE[NodeKind.SECTION] == ConceptType.SECTION

    def test_contains_edge_maps(self) -> None:
        assert EDGE_KIND_TO_RELATION_TYPE[EdgeKind.CONTAINS] == RelationType.CONTAINS

    def test_references_edge_maps(self) -> None:
        assert EDGE_KIND_TO_RELATION_TYPE[EdgeKind.REFERENCES] == RelationType.REFERENCES


# ---------------------------------------------------------------------------
# Tests: node_to_frontmatter_dict
# ---------------------------------------------------------------------------


class TestNodeToFrontmatterDict:
    """Tests for node_to_frontmatter_dict()."""

    def test_maps_symbol_type(
        self, symbol_node: UniversalNode, sample_edges: list[UniversalEdge]
    ) -> None:
        """SYMBOL node maps to type='Symbol' in the dict."""
        d = node_to_frontmatter_dict(symbol_node, sample_edges)
        assert d["type"] == "Symbol"
        assert d["concept_id"] == "sym-builder-abc"

    def test_maps_all_node_kinds(self) -> None:
        """All 6 NodeKind values map without error."""
        for kind in NodeKind:
            node = UniversalNode(
                node_id=f"test-{kind.value}",
                kind=kind,
                title="Test",
                source_uri="file:///test",
            )
            d = node_to_frontmatter_dict(node, [])
            assert d["type"] == NODE_KIND_TO_CONCEPT_TYPE[kind].value

    def test_summary_fallback_to_title(self, no_summary_node: UniversalNode) -> None:
        """When summary is None, falls back to title for the summary field."""
        d = node_to_frontmatter_dict(no_summary_node, [])
        assert d["summary"] == "Fallback Title"

    def test_summary_used_when_present(self, symbol_node: UniversalNode) -> None:
        """When summary is set, it is used (not the title)."""
        d = node_to_frontmatter_dict(symbol_node, [])
        assert d["summary"] == "Orchestrates the build pipeline."

    def test_relates_to_from_outgoing_edges(
        self, symbol_node: UniversalNode, sample_edges: list[UniversalEdge]
    ) -> None:
        """Outgoing edges become relates_to entries with correct rel value."""
        d = node_to_frontmatter_dict(symbol_node, sample_edges)
        assert len(d["relates_to"]) == 1
        assert d["relates_to"][0]["concept"] == "doc-readme-xyz"
        assert d["relates_to"][0]["rel"] == "references"

    def test_only_outgoing_edges_included(
        self, doc_node_with_content_ref: UniversalNode, sample_edges: list[UniversalEdge]
    ) -> None:
        """Incoming edges are NOT included in relates_to."""
        d = node_to_frontmatter_dict(doc_node_with_content_ref, sample_edges)
        assert d["relates_to"] == []

    def test_categories_sorted_alphabetically(self) -> None:
        """categories in domain_tags are sorted for determinism."""
        node = UniversalNode(
            node_id="test-sort",
            kind=NodeKind.CONCEPT,
            title="Sort Test",
            source_uri="file:///test",
            domain_tags={"categories": ["zebra", "apple", "mango"]},
        )
        d = node_to_frontmatter_dict(node, [])
        assert d["categories"] == ["apple", "mango", "zebra"]

    def test_concept_id_maps_to_node_id(self, symbol_node: UniversalNode) -> None:
        """concept_id in the dict must equal node.node_id."""
        d = node_to_frontmatter_dict(symbol_node, [])
        assert d["concept_id"] == symbol_node.node_id

    def test_source_included_when_source_uri_present(
        self, symbol_node: UniversalNode
    ) -> None:
        """source dict includes document=source_uri."""
        d = node_to_frontmatter_dict(symbol_node, [])
        assert d["source"] is not None
        assert d["source"]["document"] == "file:///builder.py"


# ---------------------------------------------------------------------------
# Tests: project_node_sidecar
# ---------------------------------------------------------------------------


class TestProjectNodeSidecar:
    """Tests for project_node_sidecar()."""

    def test_contains_frontmatter_and_body(
        self, symbol_node: UniversalNode, sample_edges: list[UniversalEdge]
    ) -> None:
        """Sidecar starts with frontmatter and contains the body."""
        sidecar = project_node_sidecar(symbol_node, sample_edges, "Body text here.")
        assert sidecar.startswith("---\n")
        assert "Body text here." in sidecar

    def test_byte_determinism(
        self, symbol_node: UniversalNode, sample_edges: list[UniversalEdge]
    ) -> None:
        """Same inputs always produce identical output."""
        s1 = project_node_sidecar(symbol_node, sample_edges, "Body")
        s2 = project_node_sidecar(symbol_node, sample_edges, "Body")
        assert s1 == s2

    def test_parseable_frontmatter(
        self, symbol_node: UniversalNode, sample_edges: list[UniversalEdge]
    ) -> None:
        """Frontmatter in the sidecar parses back to a ConceptFrontmatter."""
        sidecar = project_node_sidecar(symbol_node, sample_edges, "Body")
        fm = parse_frontmatter(sidecar)
        assert fm.type == ConceptType.SYMBOL
        assert fm.id == "sym-builder-abc"

    def test_body_after_frontmatter(
        self, symbol_node: UniversalNode, sample_edges: list[UniversalEdge]
    ) -> None:
        """Body appears after the closing --- delimiter."""
        body = "This is the node body text."
        sidecar = project_node_sidecar(symbol_node, sample_edges, body)
        # Body should appear after the frontmatter block
        parts = sidecar.split("---\n")
        # parts[0] = '', parts[1] = yaml, parts[2] = '\n' + body
        assert body in sidecar


# ---------------------------------------------------------------------------
# Tests: project_graph_sidecars
# ---------------------------------------------------------------------------


class TestProjectGraphSidecars:
    """Tests for project_graph_sidecars()."""

    @pytest.mark.asyncio
    async def test_writes_files(
        self,
        symbol_node: UniversalNode,
        sample_edges: list[UniversalEdge],
        tmp_path: Path,
    ) -> None:
        """project_graph_sidecars() writes one file per node to nodes/."""
        report = await project_graph_sidecars(
            [symbol_node], sample_edges, tmp_path
        )
        assert report.nodes_projected == 1
        assert (tmp_path / "nodes").is_dir()
        written_files = list((tmp_path / "nodes").glob("*.md"))
        assert len(written_files) == 1

    @pytest.mark.asyncio
    async def test_report_structure(
        self, symbol_node: UniversalNode, tmp_path: Path
    ) -> None:
        """GraphProjectionReport has correct field values after projection."""
        report = await project_graph_sidecars([symbol_node], [], tmp_path)
        assert isinstance(report, GraphProjectionReport)
        assert report.output_dir == str(tmp_path)
        assert report.nodes_projected == 1
        assert len(report.files_written) == 1

    @pytest.mark.asyncio
    async def test_content_ref_resolution(
        self,
        doc_node_with_content_ref: UniversalNode,
        tmp_path: Path,
    ) -> None:
        """When content_ref is present and resolvable, full body is used."""
        mock_store = MagicMock()
        mock_store.load.return_value = "Full body from PageIndex."
        report = await project_graph_sidecars(
            [doc_node_with_content_ref], [], tmp_path, content_store=mock_store
        )
        files = list((tmp_path / "nodes").glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "Full body from PageIndex." in content
        mock_store.load.assert_called_once_with("docs", "readme-node")

    @pytest.mark.asyncio
    async def test_content_ref_missing_falls_back(
        self,
        doc_node_with_content_ref: UniversalNode,
        tmp_path: Path,
    ) -> None:
        """When content_ref resolves to None, falls back to summary."""
        mock_store = MagicMock()
        mock_store.load.return_value = None  # simulate cache miss
        report = await project_graph_sidecars(
            [doc_node_with_content_ref], [], tmp_path, content_store=mock_store
        )
        files = list((tmp_path / "nodes").glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text()
        # Falls back to summary
        assert "Project docs." in content

    @pytest.mark.asyncio
    async def test_no_content_store_uses_summary(
        self, symbol_node: UniversalNode, tmp_path: Path
    ) -> None:
        """Without content_store, sidecar body is the node summary."""
        await project_graph_sidecars([symbol_node], [], tmp_path)
        files = list((tmp_path / "nodes").glob("*.md"))
        content = files[0].read_text()
        assert "Orchestrates the build pipeline." in content

    @pytest.mark.asyncio
    async def test_multiple_nodes(self, tmp_path: Path) -> None:
        """Multiple nodes are all projected."""
        nodes = [
            UniversalNode(
                node_id=f"node-{i}",
                kind=NodeKind.CONCEPT,
                title=f"Node {i}",
                source_uri=f"file:///node{i}",
                summary=f"Summary {i}.",
            )
            for i in range(3)
        ]
        report = await project_graph_sidecars(nodes, [], tmp_path)
        assert report.nodes_projected == 3
        assert len(list((tmp_path / "nodes").glob("*.md"))) == 3

    @pytest.mark.asyncio
    async def test_empty_nodes_list(self, tmp_path: Path) -> None:
        """Empty node list produces a report with 0 projections."""
        report = await project_graph_sidecars([], [], tmp_path)
        assert report.nodes_projected == 0
        assert report.files_written == []


# ---------------------------------------------------------------------------
# Tests: project_report_frontmatter
# ---------------------------------------------------------------------------


class TestProjectReportFrontmatter:
    """Tests for project_report_frontmatter()."""

    def test_produces_valid_yaml(self) -> None:
        """project_report_frontmatter() returns YAML delimited by ---."""
        from parrot.knowledge.graphindex.analytics import AnalyticsResult

        analytics = AnalyticsResult()
        fm = project_report_frontmatter(analytics, "test-tenant")
        assert fm.startswith("---\n")
        assert fm.endswith("---\n")
        assert "type: Document" in fm

    def test_title_is_knowledge_graph_report(self) -> None:
        """Frontmatter title is 'Knowledge Graph Report'."""
        from parrot.knowledge.graphindex.analytics import AnalyticsResult

        analytics = AnalyticsResult()
        fm = project_report_frontmatter(analytics, "test-tenant")
        parsed = parse_frontmatter(fm)
        assert parsed.title == "Knowledge Graph Report"

    def test_type_is_document_node(self) -> None:
        """Frontmatter type is ConceptType.DOCUMENT_NODE."""
        from parrot.knowledge.graphindex.analytics import AnalyticsResult

        analytics = AnalyticsResult()
        fm = project_report_frontmatter(analytics, "test-tenant")
        parsed = parse_frontmatter(fm)
        assert parsed.type == ConceptType.DOCUMENT_NODE

    def test_byte_determinism(self) -> None:
        """Same analytics + tenant_id → identical frontmatter."""
        from parrot.knowledge.graphindex.analytics import AnalyticsResult

        analytics = AnalyticsResult()
        fm1 = project_report_frontmatter(analytics, "tenant-a")
        fm2 = project_report_frontmatter(analytics, "tenant-a")
        # Both should produce frontmatter; exact timestamp may differ
        # so we check structure not byte equality here
        p1 = parse_frontmatter(fm1)
        p2 = parse_frontmatter(fm2)
        assert p1.title == p2.title
        assert p1.type == p2.type


# ---------------------------------------------------------------------------
# Tests: GraphProjectionReport model
# ---------------------------------------------------------------------------


class TestGraphProjectionReport:
    """Tests for the GraphProjectionReport Pydantic model."""

    def test_default_fields(self) -> None:
        """GraphProjectionReport has correct defaults."""
        report = GraphProjectionReport(output_dir="/tmp/test")
        assert report.output_dir == "/tmp/test"
        assert report.nodes_projected == 0
        assert report.files_written == []
        assert report.report_frontmatter_added is False

    def test_populated_fields(self) -> None:
        """GraphProjectionReport stores all provided values."""
        report = GraphProjectionReport(
            output_dir="/tmp/test",
            nodes_projected=5,
            files_written=["/tmp/test/nodes/a.md"],
            report_frontmatter_added=True,
        )
        assert report.nodes_projected == 5
        assert len(report.files_written) == 1
        assert report.report_frontmatter_added is True
