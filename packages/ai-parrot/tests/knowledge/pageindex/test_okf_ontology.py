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
        """All original 11 ontological types must still be present.

        FEAT-239 added 5 graph-native types; original values are unchanged.
        """
        original_expected = {
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
        actual = {t.value for t in ConceptType}
        assert original_expected.issubset(actual)

    def test_section_is_fallback(self):
        """SECTION is the structural fallback for unavailable classification."""
        assert ConceptType.SECTION == "Section"
        assert ConceptType.SECTION.value == "Section"

    def test_str_serialization(self):
        """Values serialize as plain strings for JSON/YAML."""
        assert ConceptType.PLAYBOOK.value == "Playbook"
        assert ConceptType.CONTROL.value == "Control"

    def test_all_values_count(self):
        """11 original + 5 graph-native (FEAT-239) + 5 wiki (FEAT-260)
        + OTHER (FEAT-216 open-vocabulary fallback) = 22."""
        assert len(list(ConceptType)) == 22

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
        """All original 8 relation types must still be present.

        FEAT-239 added 4 graph edge kinds; original values are unchanged.
        """
        original_expected = {
            "references",
            "maps_to",
            "satisfies",
            "satisfied_by",
            "supersedes",
            "superseded_by",
            "implements",
            "part_of",
        }
        actual = {r.value for r in RelationType}
        assert original_expected.issubset(actual)

    def test_references_is_default(self):
        """REFERENCES is the default fallback for untyped prose links."""
        assert RelationType.REFERENCES == "references"
        assert RelationType.REFERENCES.value == "references"

    def test_all_values_count(self):
        """8 original + 4 graph edge kinds (FEAT-239) + extends (FEAT-240)
        + summarizes/contradicts (FEAT-260) = 15."""
        assert len(list(RelationType)) == 15

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
