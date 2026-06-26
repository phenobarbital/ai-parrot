"""Employee Ontology Integration Smoke Test (TASK-1625).

Schema-level smoke test for the Employee entity added to
knowledge.ontology.yaml in TASK-1624. No ArangoDB or Redis required.
Verifies that the merged base + knowledge ontology is internally
consistent with respect to the Employee entity and the reports_to relation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.schema import MergedOntology, OntologyDefinition

# Paths to default ontology files shipped with the package
_DEFAULTS_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "parrot"
    / "knowledge"
    / "ontology"
    / "defaults"
)
_BASE_YAML = _DEFAULTS_DIR / "base.ontology.yaml"
_KNOWLEDGE_YAML = _DEFAULTS_DIR / "knowledge.ontology.yaml"


@pytest.fixture
def base_ontology() -> OntologyDefinition:
    """Load the base ontology definition from the bundled default YAML."""
    return OntologyParser.load(_BASE_YAML)


@pytest.fixture
def knowledge_ontology() -> OntologyDefinition:
    """Load the knowledge ontology definition from the bundled default YAML."""
    return OntologyParser.load(_KNOWLEDGE_YAML)


@pytest.fixture
def merged(
    base_ontology: OntologyDefinition,
    knowledge_ontology: OntologyDefinition,
) -> MergedOntology:
    """Merge base + knowledge ontology definitions into a MergedOntology."""
    return OntologyMerger().merge_definitions([base_ontology, knowledge_ontology])


class TestEmployeeOntologySmoke:
    """Smoke tests for the Employee entity in the merged ontology."""

    def test_knowledge_yaml_loads(self, knowledge_ontology: OntologyDefinition) -> None:
        """knowledge.ontology.yaml must load successfully and carry the correct name."""
        assert knowledge_ontology is not None
        assert knowledge_ontology.name == "knowledge"

    def test_employee_entity_present(self, merged: MergedOntology) -> None:
        """Employee entity must appear in the merged ontology."""
        assert "Employee" in merged.entities

    def test_employee_required_properties(self, merged: MergedOntology) -> None:
        """Merged Employee entity must include employee_id, name, and email."""
        emp = merged.entities["Employee"]
        prop_names = emp.get_property_names()
        assert "employee_id" in prop_names, (
            f"employee_id missing from Employee properties: {sorted(prop_names)}"
        )
        assert "name" in prop_names, (
            f"name missing from Employee properties: {sorted(prop_names)}"
        )
        assert "email" in prop_names, (
            f"email missing from Employee properties: {sorted(prop_names)}"
        )

    def test_reports_to_relation(self, merged: MergedOntology) -> None:
        """reports_to relation must exist and reference Employee on both ends."""
        assert "reports_to" in merged.relations, (
            "reports_to relation not found in merged ontology"
        )
        rel = merged.relations["reports_to"]
        assert rel.from_entity == "Employee", (
            f"reports_to.from_entity expected 'Employee', got '{rel.from_entity}'"
        )
        assert rel.to_entity == "Employee", (
            f"reports_to.to_entity expected 'Employee', got '{rel.to_entity}'"
        )

    def test_merge_integrity(self, merged: MergedOntology) -> None:
        """All relation endpoints must reference entities that exist in the merged ontology."""
        for rel_name, rel in merged.relations.items():
            assert rel.from_entity in merged.entities, (
                f"Relation {rel_name}: from_entity='{rel.from_entity}' not in entities"
            )
            assert rel.to_entity in merged.entities, (
                f"Relation {rel_name}: to_entity='{rel.to_entity}' not in entities"
            )
