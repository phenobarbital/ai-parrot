"""Unit tests for the shared OKF ontology module (FEAT-239).

Tests verify:
- All existing PageIndex ConceptType values are unchanged.
- New graph-native ConceptType values are present.
- All existing RelationType values are unchanged.
- New graph edge kind RelationType values are present.
- Backward-compatible re-exports from pageindex.okf still work.
"""

import pytest

from parrot.knowledge.okf.ontology import (
    ConceptType,
    RelationType,
    RelatesTo,
    SourceProvenance,
)


class TestConceptType:
    """Tests for the extended ConceptType enum."""

    def test_existing_values_unchanged(self) -> None:
        """Verify existing PageIndex type strings are not altered."""
        assert ConceptType.SECTION.value == "Section"
        assert ConceptType.POLICY.value == "Policy"
        assert ConceptType.CONTROL.value == "Control"
        assert ConceptType.SAFEGUARD.value == "Safeguard"
        assert ConceptType.EVIDENCE.value == "Evidence"
        assert ConceptType.PLAYBOOK.value == "Playbook"
        assert ConceptType.PROCEDURE.value == "Procedure"
        assert ConceptType.STANDARD.value == "Standard"
        assert ConceptType.FRAMEWORK.value == "Framework"
        assert ConceptType.REGULATION.value == "Regulation"
        assert ConceptType.GUIDELINE.value == "Guideline"

    def test_graph_native_values_exist(self) -> None:
        """Verify FEAT-239 graph-native types are present with correct strings."""
        assert ConceptType.SYMBOL.value == "Symbol"
        assert ConceptType.RATIONALE.value == "Rationale"
        assert ConceptType.SKILL.value == "Skill"
        assert ConceptType.CONCEPT_NODE.value == "Concept"
        assert ConceptType.DOCUMENT_NODE.value == "Document"

    def test_total_count(self) -> None:
        """ConceptType must have exactly 16 values (11 existing + 5 new)."""
        assert len(ConceptType) == 16

    def test_string_round_trip(self) -> None:
        """ConceptType(value) must reconstruct the correct enum member."""
        assert ConceptType("Symbol") == ConceptType.SYMBOL
        assert ConceptType("Section") == ConceptType.SECTION
        assert ConceptType("Concept") == ConceptType.CONCEPT_NODE
        assert ConceptType("Document") == ConceptType.DOCUMENT_NODE

    def test_section_unified(self) -> None:
        """SECTION must be usable for both graph and page contexts (same string)."""
        # Both NodeKind.SECTION (value="section") and ConceptType.SECTION
        # (value="Section") can coexist.  ConceptType.SECTION is the OKF label.
        assert ConceptType.SECTION.value == "Section"
        assert ConceptType("Section") == ConceptType.SECTION


class TestRelationType:
    """Tests for the extended RelationType enum."""

    def test_existing_values_unchanged(self) -> None:
        """Verify existing relation type strings are not altered."""
        assert RelationType.REFERENCES.value == "references"
        assert RelationType.MAPS_TO.value == "maps_to"
        assert RelationType.SATISFIES.value == "satisfies"
        assert RelationType.SATISFIED_BY.value == "satisfied_by"
        assert RelationType.SUPERSEDES.value == "supersedes"
        assert RelationType.SUPERSEDED_BY.value == "superseded_by"
        assert RelationType.IMPLEMENTS.value == "implements"
        assert RelationType.PART_OF.value == "part_of"

    def test_graph_edge_values_exist(self) -> None:
        """Verify FEAT-239 graph edge types are present with correct strings."""
        assert RelationType.DEFINES.value == "defines"
        assert RelationType.MENTIONS.value == "mentions"
        assert RelationType.EXPLAINS.value == "explains"
        assert RelationType.CONTAINS.value == "contains"

    def test_extends_value_exists(self) -> None:
        """Verify FEAT-240 EXTENDS relation type is present."""
        assert RelationType.EXTENDS.value == "extends"
        assert RelationType("extends") == RelationType.EXTENDS

    def test_total_count(self) -> None:
        """RelationType must have exactly 13 values (8 existing + 4 FEAT-239 + 1 FEAT-240)."""
        assert len(RelationType) == 13

    def test_string_round_trip(self) -> None:
        """RelationType(value) must reconstruct the correct enum member."""
        assert RelationType("defines") == RelationType.DEFINES
        assert RelationType("references") == RelationType.REFERENCES


class TestRelatesTo:
    """Tests for the RelatesTo Pydantic model."""

    def test_default_rel_is_references(self) -> None:
        """RelatesTo.rel defaults to REFERENCES."""
        r = RelatesTo(concept="target-id")
        assert r.rel == RelationType.REFERENCES

    def test_explicit_rel(self) -> None:
        """RelatesTo accepts an explicit RelationType."""
        r = RelatesTo(concept="target-id", rel=RelationType.DEFINES)
        assert r.rel == RelationType.DEFINES

    def test_rel_from_string(self) -> None:
        """RelatesTo.rel can be set via string value."""
        r = RelatesTo(concept="target-id", rel="mentions")  # type: ignore[arg-type]
        assert r.rel == RelationType.MENTIONS


class TestSourceProvenance:
    """Tests for the SourceProvenance Pydantic model."""

    def test_required_document(self) -> None:
        """SourceProvenance requires document field."""
        sp = SourceProvenance(document="myfile.pdf")
        assert sp.document == "myfile.pdf"
        assert sp.pages is None
        assert sp.url is None

    def test_with_pages_and_url(self) -> None:
        """SourceProvenance accepts pages and url."""
        sp = SourceProvenance(document="doc.pdf", pages=[1, 5], url="https://example.com")
        assert sp.pages == [1, 5]
        assert sp.url == "https://example.com"


class TestReExportCompat:
    """Tests for backward-compatible re-exports from pageindex.okf."""

    def test_pageindex_import_concept_type(self) -> None:
        """from parrot.knowledge.pageindex.okf import ConceptType must still work."""
        from parrot.knowledge.pageindex.okf import ConceptType as CT

        assert CT.SECTION.value == "Section"
        # New values must also be available via the re-export
        assert CT.SYMBOL.value == "Symbol"
        assert CT.DOCUMENT_NODE.value == "Document"

    def test_pageindex_import_relation_type(self) -> None:
        """from parrot.knowledge.pageindex.okf import RelationType must still work."""
        from parrot.knowledge.pageindex.okf import RelationType as RT

        assert RT.REFERENCES.value == "references"
        assert RT.DEFINES.value == "defines"

    def test_pageindex_import_relates_to(self) -> None:
        """from parrot.knowledge.pageindex.okf import RelatesTo must still work."""
        from parrot.knowledge.pageindex.okf import RelatesTo as RT

        r = RT(concept="test-id")
        assert r.rel == RelationType.REFERENCES

    def test_pageindex_import_source_provenance(self) -> None:
        """from parrot.knowledge.pageindex.okf import SourceProvenance must still work."""
        from parrot.knowledge.pageindex.okf import SourceProvenance as SP

        sp = SP(document="test.pdf")
        assert sp.document == "test.pdf"

    def test_ontology_shim_import(self) -> None:
        """from parrot.knowledge.pageindex.okf.ontology import ConceptType still works."""
        from parrot.knowledge.pageindex.okf.ontology import ConceptType as CT

        assert CT.GUIDELINE.value == "Guideline"
        assert len(CT) == 16
