"""Unit tests for the shared OKF frontmatter engine (FEAT-239).

Tests verify:
- ConceptFrontmatter model can be instantiated with all field types.
- project_frontmatter() produces valid byte-deterministic YAML frontmatter.
- parse_frontmatter() round-trips correctly.
- Backward-compatible re-exports from pageindex.okf still work.
"""

import pytest

from parrot.knowledge.okf.frontmatter import (
    ConceptFrontmatter,
    project_frontmatter,
    parse_frontmatter,
)
from parrot.knowledge.okf.ontology import ConceptType, RelationType, RelatesTo


class TestConceptFrontmatterModel:
    """Tests for the ConceptFrontmatter Pydantic model."""

    def test_create_with_required_fields(self) -> None:
        """ConceptFrontmatter can be instantiated with required fields."""
        fm = ConceptFrontmatter(
            type=ConceptType.SECTION,
            title="Test",
            id="test-id",
            node_id="n-001",
            resource="knowledge://test/test-id",
            tags=[],
            timestamp="2026-06-16T00:00:00Z",
            summary="Test summary",
            relates_to=[],
        )
        assert fm.type == ConceptType.SECTION
        assert fm.id == "test-id"
        assert fm.source is None

    def test_create_with_graph_native_type(self) -> None:
        """ConceptFrontmatter accepts graph-native ConceptType values."""
        fm = ConceptFrontmatter(
            type=ConceptType.SYMBOL,
            title="Builder",
            id="builder-id",
            node_id="sym-001",
            resource="knowledge://graphindex/sym-001",
            tags=["python"],
            timestamp="2026-06-16T00:00:00Z",
            summary="A builder class",
            relates_to=[],
        )
        assert fm.type == ConceptType.SYMBOL

    def test_create_with_document_node_type(self) -> None:
        """ConceptFrontmatter accepts DOCUMENT_NODE type from FEAT-239."""
        fm = ConceptFrontmatter(
            type=ConceptType.DOCUMENT_NODE,
            title="README",
            id="readme-id",
            node_id="doc-001",
            resource="knowledge://graphindex/doc-001",
            tags=[],
            timestamp="",
            summary="Project documentation.",
            relates_to=[],
        )
        assert fm.type == ConceptType.DOCUMENT_NODE
        assert fm.type.value == "Document"

    def test_relates_to_with_graph_edge_type(self) -> None:
        """ConceptFrontmatter.relates_to can hold graph edge relation types."""
        rel = RelatesTo(concept="target-id", rel=RelationType.DEFINES)
        fm = ConceptFrontmatter(
            type=ConceptType.SYMBOL,
            title="Test",
            id="test-id",
            node_id="n-001",
            resource="knowledge://graphindex/test-id",
            tags=[],
            timestamp="",
            summary="Test.",
            relates_to=[rel],
        )
        assert fm.relates_to[0].rel == RelationType.DEFINES


class TestProjectFrontmatter:
    """Tests for the project_frontmatter() function."""

    def test_produces_yaml_block(self) -> None:
        """project_frontmatter() returns a YAML frontmatter string."""
        node = {
            "concept_id": "test-concept",
            "type": "Section",
            "title": "Test Node",
            "node_id": "n-001",
            "summary": "A test node.",
            "categories": ["test"],
            "timestamp": "2026-06-16T00:00:00Z",
        }
        result = project_frontmatter(node, "test-tree")
        assert result.startswith("---\n")
        assert result.endswith("---\n")
        assert "type: Section" in result

    def test_byte_determinism(self) -> None:
        """Same input → identical YAML output every time."""
        node = {
            "concept_id": "det-test",
            "type": "Policy",
            "title": "Determinism",
            "node_id": "n-002",
            "summary": "Check determinism.",
            "categories": ["b", "a"],
            "timestamp": "2026-06-16T00:00:00Z",
        }
        r1 = project_frontmatter(node, "tree")
        r2 = project_frontmatter(node, "tree")
        assert r1 == r2

    def test_tags_sorted_alphabetically(self) -> None:
        """Tags are sorted alphabetically for determinism."""
        node = {
            "concept_id": "sort-test",
            "type": "Section",
            "title": "Sort Test",
            "node_id": "n-003",
            "summary": "Sorting test.",
            "categories": ["zebra", "apple", "mango"],
            "timestamp": "",
        }
        result = project_frontmatter(node, "tree")
        # Parse and verify tag order
        parsed = parse_frontmatter(result)
        assert parsed.tags == ["apple", "mango", "zebra"]

    def test_graph_native_type_accepted(self) -> None:
        """project_frontmatter() accepts graph-native ConceptType string values."""
        node = {
            "concept_id": "sym-001",
            "type": "Symbol",
            "title": "MyClass",
            "node_id": "sym-001",
            "summary": "A Python class.",
            "categories": [],
            "timestamp": "",
        }
        result = project_frontmatter(node, "graphindex")
        assert "type: Symbol" in result

    def test_requires_concept_id(self) -> None:
        """project_frontmatter() raises KeyError when concept_id is absent."""
        node = {"type": "Section", "title": "No ID", "node_id": "n-001"}
        with pytest.raises(KeyError):
            project_frontmatter(node, "tree")


class TestParseFrontmatter:
    """Tests for the parse_frontmatter() function."""

    def test_round_trip(self) -> None:
        """project_frontmatter → parse_frontmatter preserves key fields."""
        node = {
            "concept_id": "rt-test",
            "type": "Control",
            "title": "Round Trip",
            "node_id": "n-003",
            "summary": "Round trip test.",
            "categories": [],
            "timestamp": "2026-06-16T00:00:00Z",
        }
        yaml_str = project_frontmatter(node, "tree")
        parsed = parse_frontmatter(yaml_str)
        assert parsed.id == "rt-test"
        assert parsed.type == ConceptType.CONTROL
        assert parsed.title == "Round Trip"

    def test_round_trip_with_graph_native_type(self) -> None:
        """parse_frontmatter() correctly reconstructs graph-native types."""
        node = {
            "concept_id": "doc-001",
            "type": "Document",
            "title": "README",
            "node_id": "doc-001",
            "summary": "Project docs.",
            "categories": [],
            "timestamp": "",
        }
        yaml_str = project_frontmatter(node, "graphindex")
        parsed = parse_frontmatter(yaml_str)
        assert parsed.type == ConceptType.DOCUMENT_NODE

    def test_raises_on_missing_delimiter(self) -> None:
        """parse_frontmatter() raises ValueError when no frontmatter found."""
        with pytest.raises(ValueError, match="---"):
            parse_frontmatter("No frontmatter here\nJust body text.")

    def test_raises_on_no_closing_delimiter(self) -> None:
        """parse_frontmatter() raises ValueError when closing --- is absent."""
        with pytest.raises(ValueError):
            parse_frontmatter("---\ntype: Section\n# No closing delimiter")


class TestReExportCompat:
    """Tests for backward-compatible re-exports from pageindex.okf."""

    def test_concept_frontmatter_import(self) -> None:
        """from parrot.knowledge.pageindex.okf import ConceptFrontmatter works."""
        from parrot.knowledge.pageindex.okf import ConceptFrontmatter as CF

        fm = CF(
            type=ConceptType.SECTION,
            title="T",
            id="id",
            node_id="n",
            resource="pageindex://t/id",
            tags=[],
            timestamp="",
            summary="s",
            relates_to=[],
        )
        assert fm.id == "id"

    def test_project_frontmatter_import(self) -> None:
        """from parrot.knowledge.pageindex.okf import project_frontmatter works."""
        from parrot.knowledge.pageindex.okf import project_frontmatter as pf

        node = {
            "concept_id": "compat-test",
            "type": "Section",
            "title": "Compat",
            "node_id": "n-001",
            "summary": "Compat test.",
            "categories": [],
            "timestamp": "",
        }
        result = pf(node, "tree")
        assert result.startswith("---\n")

    def test_parse_frontmatter_import(self) -> None:
        """from parrot.knowledge.pageindex.okf import parse_frontmatter works."""
        from parrot.knowledge.pageindex.okf import parse_frontmatter as pfm

        node = {
            "concept_id": "parse-compat",
            "type": "Policy",
            "title": "Policy Node",
            "node_id": "n-002",
            "summary": "A policy.",
            "categories": [],
            "timestamp": "",
        }
        from parrot.knowledge.pageindex.okf import project_frontmatter as pf
        yaml_str = pf(node, "tree")
        parsed = pfm(yaml_str)
        assert parsed.id == "parse-compat"
