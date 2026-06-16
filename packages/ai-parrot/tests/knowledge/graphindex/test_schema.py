"""Unit tests for parrot.knowledge.graphindex.schema."""

import pytest
from pydantic import ValidationError

from parrot.knowledge.graphindex.schema import (
    BuildResult,
    EdgeKind,
    IngestResult,
    NodeKind,
    Provenance,
    SourceConfig,
    UniversalEdge,
    UniversalNode,
)


class TestProvenance:
    def test_all_values_defined(self):
        assert Provenance.EXTRACTED.value == "extracted"
        assert Provenance.INFERRED.value == "inferred"
        assert Provenance.AMBIGUOUS.value == "ambiguous"


class TestNodeKind:
    def test_all_six_values(self):
        kinds = {k.value for k in NodeKind}
        assert kinds == {"document", "section", "symbol", "concept", "rationale", "skill"}


class TestEdgeKind:
    def test_all_five_values(self):
        kinds = {k.value for k in EdgeKind}
        # FEAT-240 (TASK-1571) added "extends" for Odoo model inheritance edges
        assert kinds == {"contains", "references", "defines", "mentions", "explains", "extends"}


class TestUniversalNode:
    def test_valid_node(self):
        node = UniversalNode(
            node_id="n1",
            kind=NodeKind.SYMBOL,
            title="func",
            source_uri="file.py",
        )
        assert node.provenance == Provenance.EXTRACTED

    def test_default_domain_tags(self):
        node = UniversalNode(
            node_id="n1",
            kind=NodeKind.DOCUMENT,
            title="doc",
            source_uri="doc.pdf",
        )
        assert node.domain_tags == {}

    def test_optional_fields_default_none(self):
        node = UniversalNode(
            node_id="n1",
            kind=NodeKind.SECTION,
            title="section",
            source_uri="doc.md",
        )
        assert node.content_ref is None
        assert node.summary is None
        assert node.embedding_ref is None
        assert node.parent_id is None

    def test_all_node_kinds_accepted(self):
        for kind in NodeKind:
            node = UniversalNode(
                node_id="n",
                kind=kind,
                title="t",
                source_uri="s",
            )
            assert node.kind == kind

    def test_domain_tags_arbitrary_dict(self):
        node = UniversalNode(
            node_id="n1",
            kind=NodeKind.SYMBOL,
            title="cls",
            source_uri="f.py",
            domain_tags={"symbol_type": "class", "line": 42},
        )
        assert node.domain_tags["symbol_type"] == "class"

    def test_provenance_ambiguous(self):
        node = UniversalNode(
            node_id="n1",
            kind=NodeKind.SYMBOL,
            title="broken",
            source_uri="bad.py",
            provenance=Provenance.AMBIGUOUS,
        )
        assert node.provenance == Provenance.AMBIGUOUS

    def test_missing_required_fields_raises(self):
        with pytest.raises(ValidationError):
            UniversalNode(kind=NodeKind.DOCUMENT, title="x", source_uri="y")


class TestUniversalEdge:
    def test_extracted_no_confidence(self):
        edge = UniversalEdge(
            source_id="a",
            target_id="b",
            kind=EdgeKind.CONTAINS,
        )
        assert edge.confidence is None
        assert edge.provenance == Provenance.EXTRACTED

    def test_inferred_requires_confidence(self):
        edge = UniversalEdge(
            source_id="a",
            target_id="b",
            kind=EdgeKind.MENTIONS,
            provenance=Provenance.INFERRED,
            confidence=0.85,
        )
        assert edge.confidence == 0.85

    def test_inferred_missing_confidence_raises(self):
        with pytest.raises(ValidationError):
            UniversalEdge(
                source_id="a",
                target_id="b",
                kind=EdgeKind.MENTIONS,
                provenance=Provenance.INFERRED,
                # confidence not provided
            )

    def test_extracted_with_confidence_raises(self):
        with pytest.raises(ValidationError):
            UniversalEdge(
                source_id="a",
                target_id="b",
                kind=EdgeKind.CONTAINS,
                provenance=Provenance.EXTRACTED,
                confidence=0.9,
            )

    def test_ambiguous_no_confidence(self):
        edge = UniversalEdge(
            source_id="a",
            target_id="b",
            kind=EdgeKind.REFERENCES,
            provenance=Provenance.AMBIGUOUS,
        )
        assert edge.confidence is None

    def test_all_edge_kinds_accepted(self):
        for kind in EdgeKind:
            edge = UniversalEdge(source_id="a", target_id="b", kind=kind)
            assert edge.kind == kind


class TestSourceConfig:
    def test_defaults(self):
        cfg = SourceConfig(tenant_id="t1")
        assert cfg.code_paths == []
        assert cfg.loader_sources == []
        assert cfg.skill_paths == []
        assert cfg.ignore_file is None

    def test_with_paths(self):
        cfg = SourceConfig(
            tenant_id="t1",
            code_paths=["/src"],
            loader_sources=["doc.pdf"],
        )
        assert "/src" in cfg.code_paths


class TestBuildResult:
    def test_defaults(self):
        result = BuildResult(tenant_id="t1")
        assert result.node_count == 0
        assert result.edge_count == 0
        assert result.inferred_edge_count == 0
        assert result.report_path is None
        assert result.errors == []


class TestIngestResult:
    def test_defaults(self):
        result = IngestResult(tenant_id="t1", document_uri="doc.pdf")
        assert result.nodes_replaced == 0
        assert result.edges_replaced == 0
        assert result.errors == []
