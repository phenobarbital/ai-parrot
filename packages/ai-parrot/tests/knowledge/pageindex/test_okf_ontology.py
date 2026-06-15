"""Unit tests for OKF ontology module (TASK-1552).

Tests verify:
- ConceptType enum has all 11 values; SECTION is the structural fallback.
- RelationType enum has all 8 values; REFERENCES is the default.
- RelatesTo model validates correctly.
- SourceProvenance model validates correctly.
- Public re-export from the okf package works.
"""

import pytest
from parrot.knowledge.pageindex.okf.ontology import (
    ConceptType,
    RelationType,
    RelatesTo,
    SourceProvenance,
)


class TestConceptType:
    """Tests for ConceptType controlled vocabulary."""

    def test_all_values_present(self):
        """All 11 ontological types must be present."""
        expected = {
            "Section",
            "Policy",
            "Control",
            "Safeguard",
            "Evidence",
            "Playbook",
            "Procedure",
            "Standard",
            "Framework",
            "Regulation",
            "Guideline",
        }
        assert {t.value for t in ConceptType} == expected

    def test_section_is_fallback(self):
        """SECTION is the structural fallback for unavailable classification."""
        assert ConceptType.SECTION == "Section"
        assert ConceptType.SECTION.value == "Section"

    def test_str_serialization(self):
        """Values serialize as plain strings for JSON/YAML."""
        assert ConceptType.PLAYBOOK.value == "Playbook"
        assert ConceptType.CONTROL.value == "Control"

    def test_all_values_count(self):
        """Exactly 11 values in the enum."""
        assert len(list(ConceptType)) == 11

    def test_case_sensitive_values(self):
        """Values use Title-Case as per spec."""
        for ct in ConceptType:
            assert ct.value[0].isupper(), f"{ct.value} should start with uppercase"

    def test_str_enum_equality(self):
        """str, Enum values compare equal to plain strings."""
        assert ConceptType.POLICY == "Policy"
        assert ConceptType.REGULATION == "Regulation"


class TestRelationType:
    """Tests for RelationType typed edge vocabulary."""

    def test_all_values_present(self):
        """All 8 relation types must be present."""
        expected = {
            "references",
            "maps_to",
            "satisfies",
            "satisfied_by",
            "supersedes",
            "superseded_by",
            "implements",
            "part_of",
        }
        assert {r.value for r in RelationType} == expected

    def test_references_is_default(self):
        """REFERENCES is the default fallback for untyped prose links."""
        assert RelationType.REFERENCES == "references"
        assert RelationType.REFERENCES.value == "references"

    def test_all_values_count(self):
        """Exactly 8 values in the enum."""
        assert len(list(RelationType)) == 8

    def test_str_enum_equality(self):
        """str, Enum values compare equal to plain strings."""
        assert RelationType.MAPS_TO == "maps_to"
        assert RelationType.SATISFIES == "satisfies"


class TestRelatesTo:
    """Tests for RelatesTo typed edge model."""

    def test_valid_edge(self):
        """RelatesTo validates with concept and rel fields."""
        edge = RelatesTo(concept="controls/nist-ir-4", rel=RelationType.MAPS_TO)
        assert edge.concept == "controls/nist-ir-4"
        assert edge.rel == RelationType.MAPS_TO

    def test_default_rel_is_references(self):
        """Default rel is REFERENCES when not specified."""
        edge = RelatesTo(concept="some-concept")
        assert edge.rel == RelationType.REFERENCES

    def test_rejects_missing_concept(self):
        """concept is a required field."""
        with pytest.raises(Exception):
            RelatesTo()

    def test_rel_accepts_string_value(self):
        """rel can be set via string value for JSON deserialization."""
        edge = RelatesTo(concept="a/b", rel="satisfies")
        assert edge.rel == RelationType.SATISFIES

    def test_model_dump(self):
        """model_dump produces expected dict."""
        edge = RelatesTo(concept="controls/nist-ir-4", rel=RelationType.MAPS_TO)
        d = edge.model_dump()
        assert d["concept"] == "controls/nist-ir-4"
        assert d["rel"] == "maps_to"


class TestSourceProvenance:
    """Tests for SourceProvenance per-node provenance model."""

    def test_full_provenance(self):
        """SourceProvenance with all fields."""
        src = SourceProvenance(
            document="guide.pdf",
            pages=[43, 47],
            url="https://example.com",
        )
        assert src.document == "guide.pdf"
        assert src.pages == [43, 47]
        assert src.url == "https://example.com"

    def test_minimal_provenance(self):
        """SourceProvenance with only required document field."""
        src = SourceProvenance(document="guide.pdf")
        assert src.document == "guide.pdf"
        assert src.pages is None
        assert src.url is None

    def test_rejects_missing_document(self):
        """document is a required field."""
        with pytest.raises(Exception):
            SourceProvenance()

    def test_model_dump(self):
        """model_dump excludes None fields correctly."""
        src = SourceProvenance(document="doc.pdf")
        d = src.model_dump()
        assert d["document"] == "doc.pdf"
        assert d["pages"] is None
        assert d["url"] is None


class TestPackageReexports:
    """Tests for public re-exports from the okf package."""

    def test_import_from_package(self):
        """All public symbols are re-exported from the okf package."""
        from parrot.knowledge.pageindex.okf import (
            ConceptType,
            RelationType,
            RelatesTo,
            SourceProvenance,
        )

        assert ConceptType.SECTION == "Section"
        assert RelationType.REFERENCES == "references"
        edge = RelatesTo(concept="x")
        assert edge.concept == "x"
        src = SourceProvenance(document="doc.pdf")
        assert src.document == "doc.pdf"
