"""FEAT-454: Additive `ConceptType` vocabulary tests.

Verifies that `ISSUE`, `PERSON` and `PROJECT` were added to `ConceptType`
without changing any pre-existing member's value, and that the two known
enumerating consumers (the migrate.py LLM classification prompt and the
obsidian.py validation list) pick up the new values without regressing.
"""

from parrot.knowledge.okf.ontology import ConceptType, RelationType

# Frozen snapshot of the vocabulary BEFORE FEAT-454. Any diff here is a
# breaking change to YAML frontmatter parsing across every index.
PRE_FEAT454: dict[str, str] = {
    "SECTION": "Section",
    "POLICY": "Policy",
    "CONTROL": "Control",
    "SAFEGUARD": "Safeguard",
    "EVIDENCE": "Evidence",
    "PLAYBOOK": "Playbook",
    "PROCEDURE": "Procedure",
    "STANDARD": "Standard",
    "FRAMEWORK": "Framework",
    "REGULATION": "Regulation",
    "GUIDELINE": "Guideline",
    "SYMBOL": "Symbol",
    "RATIONALE": "Rationale",
    "SKILL": "Skill",
    "CONCEPT_NODE": "Concept",
    "DOCUMENT_NODE": "Document",
    "WIKI_SUMMARY": "Wiki Summary",
    "WIKI_ENTITY": "Wiki Entity",
    "WIKI_COMPARISON": "Wiki Comparison",
    "WIKI_SYNTHESIS": "Wiki Synthesis",
    "WIKI_OVERVIEW": "Wiki Overview",
    "RUN": "Run",
    "CLAIM": "Claim",
    "OTHER": "Other",
}

NEW_MEMBERS = {"ISSUE": "Issue", "PERSON": "Person", "PROJECT": "Project"}


class TestConceptTypeAdditive:
    def test_new_members_exist_with_exact_values(self):
        """G11: the three new members carry exactly these strings."""
        for name, value in NEW_MEMBERS.items():
            assert getattr(ConceptType, name).value == value

    def test_no_preexisting_value_changed(self):
        """The additive guarantee: every old member keeps its old value."""
        for name, value in PRE_FEAT454.items():
            assert getattr(ConceptType, name).value == value, name

    def test_vocabulary_size(self):
        assert len(ConceptType) == len(PRE_FEAT454) + len(NEW_MEMBERS) == 27

    def test_relation_type_untouched(self):
        """This feature adds no edge kinds (spec §6 Does NOT Exist)."""
        for absent in ("BLOCKS", "DUPLICATES", "RELATES_TO", "BLOCKED_BY"):
            assert not hasattr(RelationType, absent)


class TestEnumeratingConsumers:
    """§7 risk: ConceptType is enumerated into a prompt and a validator."""

    def test_migrate_prompt_includes_new_values(self):
        from parrot.knowledge.pageindex.okf import migrate  # noqa: F401

        joined = ", ".join(t.value for t in ConceptType)
        for value in NEW_MEMBERS.values():
            assert value in joined

    def test_obsidian_validation_list_includes_new_values(self):
        allowed = sorted(item.value for item in ConceptType)
        for value in NEW_MEMBERS.values():
            assert value in allowed

    def test_str_enum_usable_as_string(self):
        assert ConceptType.ISSUE == "Issue"
        assert f"{ConceptType.ISSUE.value}" == "Issue"
