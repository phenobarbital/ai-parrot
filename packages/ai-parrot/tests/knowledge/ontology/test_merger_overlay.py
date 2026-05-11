"""Unit tests for OntologyMerger.merge_with_overlay (TASK-1086)."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from parrot.knowledge.ontology.exceptions import FrameworkOverrideError
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.schema import EntityDef, OntologyDefinition, RelationDef, TraversalPattern


@pytest.fixture
def merger() -> OntologyMerger:
    return OntologyMerger()


@pytest.fixture
def base_yaml(tmp_path: Path) -> Path:
    """Minimal base YAML with Employee and Department entities."""
    content = textwrap.dedent("""
        name: base
        version: "1.0"
        entities:
          Employee:
            collection: employees
            key_field: employee_id
            properties:
              - employee_id:
                  type: string
                  required: true
          Department:
            collection: departments
            key_field: dept_id
            properties:
              - dept_id:
                  type: string
                  required: true
        relations:
          belongs_to:
            from: Employee
            to: Department
            edge_collection: belongs_to
        traversal_patterns:
          find_team:
            description: Find team members
            query_template: "FOR v IN 1..2 OUTBOUND @start belongs_to RETURN v"
    """)
    p = tmp_path / "base.ontology.yaml"
    p.write_text(content)
    return p


@pytest.fixture
def base_yaml_paths(base_yaml: Path) -> list[Path]:
    return [base_yaml]


class TestMergeWithOverlayEmptyOverlay:
    def test_empty_overlay_matches_merge(self, merger: OntologyMerger, base_yaml_paths: list[Path]) -> None:
        """Empty overlay produces identical result to merge()."""
        from_merge = merger.merge(base_yaml_paths)
        from_overlay = merger.merge_with_overlay(base_yaml_paths, [])

        assert set(from_merge.entities.keys()) == set(from_overlay.entities.keys())
        assert set(from_merge.relations.keys()) == set(from_overlay.relations.keys())
        assert set(from_merge.traversal_patterns.keys()) == set(from_overlay.traversal_patterns.keys())

    def test_empty_overlay_same_layers(self, merger: OntologyMerger, base_yaml_paths: list[Path]) -> None:
        from_merge = merger.merge(base_yaml_paths)
        from_overlay = merger.merge_with_overlay(base_yaml_paths, [])
        assert from_merge.layers == from_overlay.layers


class TestMergeWithOverlayNewContent:
    def test_overlay_adds_new_entity(self, merger: OntologyMerger, base_yaml_paths: list[Path]) -> None:
        """Overlay with new entity_type merges successfully."""
        overlay = OntologyDefinition(
            name="pg_overlay",
            entities={"Project": EntityDef(collection="projects")},
        )
        result = merger.merge_with_overlay(base_yaml_paths, [overlay])
        assert "Project" in result.entities
        assert "Employee" in result.entities  # base preserved

    def test_overlay_adds_new_traversal_pattern(
        self, merger: OntologyMerger, base_yaml_paths: list[Path]
    ) -> None:
        """Overlay with new traversal pattern merges successfully."""
        overlay = OntologyDefinition(
            name="pg_overlay",
            traversal_patterns={
                "project_members": TraversalPattern(
                    description="Get project members",
                    query_template="FOR v IN 1..1 OUTBOUND @start works_on RETURN v",
                )
            },
        )
        result = merger.merge_with_overlay(base_yaml_paths, [overlay])
        assert "project_members" in result.traversal_patterns

    def test_multiple_overlays_merged_in_order(
        self, merger: OntologyMerger, base_yaml_paths: list[Path]
    ) -> None:
        """Multiple overlay defs are merged left-to-right."""
        overlay1 = OntologyDefinition(
            name="overlay1",
            entities={"Project": EntityDef(collection="projects")},
        )
        overlay2 = OntologyDefinition(
            name="overlay2",
            entities={"Contract": EntityDef(collection="contracts")},
        )
        result = merger.merge_with_overlay(base_yaml_paths, [overlay1, overlay2])
        assert "Project" in result.entities
        assert "Contract" in result.entities
        assert "Employee" in result.entities  # base preserved


class TestMergeWithOverlayFrameworkGuard:
    def test_framework_entity_override_blocked(
        self, merger: OntologyMerger, base_yaml_paths: list[Path]
    ) -> None:
        """Overlay redefining a base entity raises FrameworkOverrideError."""
        overlay = OntologyDefinition(
            name="pg_overlay",
            entities={"Employee": EntityDef(collection="employees_v2")},
        )
        with pytest.raises(FrameworkOverrideError) as exc_info:
            merger.merge_with_overlay(base_yaml_paths, [overlay])
        assert exc_info.value.entity_name == "Employee"

    def test_framework_relation_override_blocked(
        self, merger: OntologyMerger, base_yaml_paths: list[Path]
    ) -> None:
        """Overlay redefining a base relation raises FrameworkOverrideError."""
        overlay = OntologyDefinition(
            name="pg_overlay",
            relations={
                "belongs_to": RelationDef(**{
                    "from": "Employee",
                    "to": "Department",
                    "edge_collection": "belongs_v2",
                })
            },
        )
        with pytest.raises(FrameworkOverrideError) as exc_info:
            merger.merge_with_overlay(base_yaml_paths, [overlay])
        assert exc_info.value.entity_name == "belongs_to"

    def test_framework_pattern_override_blocked(
        self, merger: OntologyMerger, base_yaml_paths: list[Path]
    ) -> None:
        """Overlay redefining a base traversal pattern raises FrameworkOverrideError."""
        overlay = OntologyDefinition(
            name="pg_overlay",
            traversal_patterns={
                "find_team": TraversalPattern(
                    description="Override find_team",
                    query_template="FOR v IN 1..5 OUTBOUND @start belongs_to RETURN v",
                )
            },
        )
        with pytest.raises(FrameworkOverrideError):
            merger.merge_with_overlay(base_yaml_paths, [overlay])

    def test_department_entity_override_blocked(
        self, merger: OntologyMerger, base_yaml_paths: list[Path]
    ) -> None:
        """Overlay redefining Department (framework) raises FrameworkOverrideError."""
        overlay = OntologyDefinition(
            name="pg_overlay",
            entities={"Department": EntityDef(collection="depts_v2")},
        )
        with pytest.raises(FrameworkOverrideError):
            merger.merge_with_overlay(base_yaml_paths, [overlay])
