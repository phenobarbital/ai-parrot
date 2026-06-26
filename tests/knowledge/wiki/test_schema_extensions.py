"""Tests for OKF schema extensions added in TASK-1628 (FEAT-260).

Verifies that:
- ConceptType has the 5 new wiki-specific values.
- RelationType has SUMMARIZES and CONTRADICTS (but SUPERSEDES is not duplicated).
- NodeKind has WIKI_PAGE.
- All existing values remain unchanged.
"""

import pytest
from parrot.knowledge.okf.ontology import ConceptType, RelationType
from parrot.knowledge.graphindex import NodeKind


class TestWikiConceptTypes:
    """Tests for new ConceptType wiki values."""

    def test_wiki_summary_exists(self):
        """WIKI_SUMMARY value is 'Wiki Summary'."""
        assert ConceptType.WIKI_SUMMARY.value == "Wiki Summary"

    def test_wiki_entity_exists(self):
        """WIKI_ENTITY value is 'Wiki Entity'."""
        assert ConceptType.WIKI_ENTITY.value == "Wiki Entity"

    def test_wiki_comparison_exists(self):
        """WIKI_COMPARISON value is 'Wiki Comparison'."""
        assert ConceptType.WIKI_COMPARISON.value == "Wiki Comparison"

    def test_wiki_synthesis_exists(self):
        """WIKI_SYNTHESIS value is 'Wiki Synthesis'."""
        assert ConceptType.WIKI_SYNTHESIS.value == "Wiki Synthesis"

    def test_wiki_overview_exists(self):
        """WIKI_OVERVIEW value is 'Wiki Overview'."""
        assert ConceptType.WIKI_OVERVIEW.value == "Wiki Overview"

    def test_five_new_wiki_values(self):
        """Exactly 5 wiki-specific ConceptType values were added."""
        wiki_types = [
            ct for ct in ConceptType
            if ct.value.startswith("Wiki ")
        ]
        assert len(wiki_types) == 5

    def test_existing_values_unchanged(self):
        """Pre-existing ConceptType values have not changed."""
        assert ConceptType.SECTION.value == "Section"
        assert ConceptType.POLICY.value == "Policy"
        assert ConceptType.CONTROL.value == "Control"
        assert ConceptType.SYMBOL.value == "Symbol"
        assert ConceptType.RATIONALE.value == "Rationale"
        assert ConceptType.SKILL.value == "Skill"
        assert ConceptType.CONCEPT_NODE.value == "Concept"
        assert ConceptType.DOCUMENT_NODE.value == "Document"

    def test_concept_type_is_str_enum(self):
        """Wiki ConceptType values compare equal to plain strings."""
        assert ConceptType.WIKI_SUMMARY == "Wiki Summary"
        assert ConceptType.WIKI_ENTITY == "Wiki Entity"


class TestWikiRelationTypes:
    """Tests for new RelationType wiki values."""

    def test_summarizes_exists(self):
        """SUMMARIZES value is 'summarizes'."""
        assert RelationType.SUMMARIZES.value == "summarizes"

    def test_contradicts_exists(self):
        """CONTRADICTS value is 'contradicts'."""
        assert RelationType.CONTRADICTS.value == "contradicts"

    def test_supersedes_still_exists(self):
        """SUPERSEDES (pre-existing at line 75) is not duplicated or removed."""
        assert RelationType.SUPERSEDES.value == "supersedes"

    def test_supersedes_not_duplicated(self):
        """SUPERSEDES appears exactly once in the enum."""
        supersedes_values = [
            rt for rt in RelationType if rt.value == "supersedes"
        ]
        assert len(supersedes_values) == 1

    def test_existing_relations_unchanged(self):
        """Pre-existing RelationType values have not changed."""
        assert RelationType.REFERENCES.value == "references"
        assert RelationType.MAPS_TO.value == "maps_to"
        assert RelationType.EXTENDS.value == "extends"
        assert RelationType.SUPERSEDED_BY.value == "superseded_by"

    def test_relation_type_is_str_enum(self):
        """Wiki RelationType values compare equal to plain strings."""
        assert RelationType.SUMMARIZES == "summarizes"
        assert RelationType.CONTRADICTS == "contradicts"


class TestNodeKindWikiPage:
    """Tests for the WIKI_PAGE addition to NodeKind."""

    def test_wiki_page_exists(self):
        """WIKI_PAGE value is 'wiki_page'."""
        assert NodeKind.WIKI_PAGE.value == "wiki_page"

    def test_node_kind_is_str_enum(self):
        """WIKI_PAGE compares equal to the plain string 'wiki_page'."""
        assert NodeKind.WIKI_PAGE == "wiki_page"

    def test_existing_kinds_unchanged(self):
        """Pre-existing NodeKind values have not changed."""
        assert NodeKind.DOCUMENT.value == "document"
        assert NodeKind.SECTION.value == "section"
        assert NodeKind.SYMBOL.value == "symbol"
        assert NodeKind.CONCEPT.value == "concept"
        assert NodeKind.RATIONALE.value == "rationale"
        assert NodeKind.SKILL.value == "skill"

    def test_seven_node_kinds(self):
        """NodeKind now has exactly 7 members (6 original + WIKI_PAGE)."""
        assert len(NodeKind) == 7
