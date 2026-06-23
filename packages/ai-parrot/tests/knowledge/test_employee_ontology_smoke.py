"""Employee ontology integration smoke tests (FEAT-255 / NAV-8350).

Validates that:

- ``knowledge.ontology.yaml`` loads without errors via ``OntologyParser``.
- Merging ``base`` + ``knowledge`` layers produces a valid ``MergedOntology``.
- The ``Employee`` entity is present in the merged ontology with all required
  properties (``employee_id``, ``name``, ``email``, ``team``, ``role``).
- The ``reports_to`` relation exists and links Employee → Employee.
- The ``member_of`` relation exists and links Employee → Team.
- All relation endpoints reference known entities (integrity check).

No ArangoDB or Redis instance is required — tests are schema-only.
"""
from __future__ import annotations

import pytest

from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.schema import MergedOntology, OntologyDefinition


@pytest.fixture
def base_ontology() -> OntologyDefinition:
    """Load the bundled base ontology layer."""
    return OntologyParser.load_default("base")


@pytest.fixture
def knowledge_ontology() -> OntologyDefinition:
    """Load the bundled knowledge ontology layer."""
    return OntologyParser.load_default("knowledge")


@pytest.fixture
def merged(
    base_ontology: OntologyDefinition,
    knowledge_ontology: OntologyDefinition,
) -> MergedOntology:
    """Merge base + knowledge layers into a single MergedOntology."""
    return OntologyMerger().merge_definitions([base_ontology, knowledge_ontology])


class TestEmployeeOntologySmoke:
    """Schema-level smoke tests for the Employee KB ontology path."""

    def test_knowledge_yaml_loads(
        self, knowledge_ontology: OntologyDefinition
    ) -> None:
        """knowledge.ontology.yaml must load without errors."""
        assert knowledge_ontology is not None
        assert knowledge_ontology.name == "knowledge"

    def test_employee_entity_present(self, merged: MergedOntology) -> None:
        """Employee entity must be present in the merged ontology."""
        assert "Employee" in merged.entities

    def test_employee_required_properties(self, merged: MergedOntology) -> None:
        """Employee entity must have employee_id, name, and email properties."""
        emp = merged.entities["Employee"]
        prop_names = emp.get_property_names()
        assert "employee_id" in prop_names, (
            f"'employee_id' missing from Employee properties: {prop_names}"
        )
        assert "name" in prop_names, (
            f"'name' missing from Employee properties: {prop_names}"
        )
        assert "email" in prop_names, (
            f"'email' missing from Employee properties: {prop_names}"
        )

    def test_employee_team_and_role_properties(self, merged: MergedOntology) -> None:
        """Employee entity must have team and role properties (added by knowledge layer)."""
        emp = merged.entities["Employee"]
        prop_names = emp.get_property_names()
        assert "team" in prop_names, (
            f"'team' missing from Employee properties: {prop_names}"
        )
        assert "role" in prop_names, (
            f"'role' missing from Employee properties: {prop_names}"
        )

    def test_team_entity_present(self, merged: MergedOntology) -> None:
        """Team entity must be present in the merged ontology (added by knowledge layer)."""
        assert "Team" in merged.entities

    def test_reports_to_relation(self, merged: MergedOntology) -> None:
        """reports_to relation must link Employee → Employee."""
        assert "reports_to" in merged.relations, (
            "reports_to relation missing from merged ontology"
        )
        rel = merged.relations["reports_to"]
        assert rel.from_entity == "Employee"
        assert rel.to_entity == "Employee"

    def test_member_of_relation(self, merged: MergedOntology) -> None:
        """member_of relation must link Employee → Team (added by knowledge layer)."""
        assert "member_of" in merged.relations, (
            "member_of relation missing from merged ontology"
        )
        rel = merged.relations["member_of"]
        assert rel.from_entity == "Employee"
        assert rel.to_entity == "Team"

    def test_employee_team_workload_pattern(self, merged: MergedOntology) -> None:
        """employee_team_workload traversal pattern must be present."""
        assert "employee_team_workload" in merged.traversal_patterns, (
            "employee_team_workload pattern missing from merged ontology"
        )
        pattern = merged.traversal_patterns["employee_team_workload"]
        assert len(pattern.trigger_intents) > 0
        assert any(
            "team" in intent for intent in pattern.trigger_intents
        ), f"No 'team' trigger_intent found: {pattern.trigger_intents}"

    def test_merge_integrity(self, merged: MergedOntology) -> None:
        """All relation endpoints must reference entities that exist in the merged ontology."""
        entity_names = set(merged.entities.keys())
        for rel_name, rel in merged.relations.items():
            assert rel.from_entity in entity_names, (
                f"Relation '{rel_name}': from_entity='{rel.from_entity}' "
                f"not found in merged entities: {sorted(entity_names)}"
            )
            assert rel.to_entity in entity_names, (
                f"Relation '{rel_name}': to_entity='{rel.to_entity}' "
                f"not found in merged entities: {sorted(entity_names)}"
            )

    def test_merge_produces_valid_layers(self, merged: MergedOntology) -> None:
        """Merged ontology must record both YAML layers."""
        assert len(merged.layers) == 2, (
            f"Expected 2 layers, got {len(merged.layers)}: {merged.layers}"
        )
