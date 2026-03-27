"""Tests for ontology YAML merger."""
import pytest

from parrot.knowledge.ontology.exceptions import (
    OntologyIntegrityError,
    OntologyMergeError,
)
from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.schema import (
    DiscoveryConfig,
    DiscoveryRule,
    EntityDef,
    OntologyDefinition,
    PropertyDef,
    RelationDef,
    TraversalPattern,
)


@pytest.fixture
def base_ontology() -> OntologyDefinition:
    """Base ontology layer with Employee and Department."""
    return OntologyDefinition(
        name="base",
        entities={
            "Employee": EntityDef(
                collection="employees",
                key_field="employee_id",
                properties=[
                    {"name": PropertyDef(type="string", required=True)},
                    {"email": PropertyDef(type="string")},
                ],
                vectorize=["name"],
            ),
            "Department": EntityDef(
                collection="departments",
                key_field="dept_id",
                properties=[
                    {"dept_id": PropertyDef(type="string")},
                    {"name": PropertyDef(type="string")},
                ],
            ),
        },
        relations={
            "belongs_to": RelationDef(
                from_entity="Employee",
                to_entity="Department",
                edge_collection="belongs_to_dept",
                discovery=DiscoveryConfig(
                    rules=[
                        DiscoveryRule(
                            source_field="department",
                            target_field="dept_id",
                            match_type="exact",
                        )
                    ]
                ),
            ),
        },
        traversal_patterns={
            "find_dept": TraversalPattern(
                description="Find department",
                trigger_intents=["my department"],
                query_template="FOR v IN 1..1 OUTBOUND @uid belongs_to_dept RETURN v",
            ),
        },
    )


@pytest.fixture
def domain_ontology() -> OntologyDefinition:
    """Domain layer extending Employee and adding Project."""
    return OntologyDefinition(
        name="field_services",
        extends="base",
        entities={
            "Employee": EntityDef(
                extend=True,
                properties=[
                    {"project_code": PropertyDef(type="string")},
                ],
            ),
            "Project": EntityDef(
                collection="projects",
                key_field="project_id",
                properties=[
                    {"project_id": PropertyDef(type="string")},
                    {"name": PropertyDef(type="string")},
                    {"portal_url": PropertyDef(type="string")},
                ],
                vectorize=["name"],
            ),
        },
        relations={
            "assigned_to": RelationDef(
                from_entity="Employee",
                to_entity="Project",
                edge_collection="assigned_to",
                discovery=DiscoveryConfig(
                    rules=[
                        DiscoveryRule(
                            source_field="project_code",
                            target_field="project_id",
                        )
                    ]
                ),
            ),
        },
        traversal_patterns={
            "find_dept": TraversalPattern(
                description="Find department (domain override)",
                trigger_intents=["which department"],
                query_template="FOR v IN 1..1 OUTBOUND @uid belongs_to_dept RETURN v.name",
            ),
            "find_project": TraversalPattern(
                description="Find project",
                trigger_intents=["my project"],
                query_template="FOR v IN 1..1 OUTBOUND @uid assigned_to RETURN v",
            ),
        },
    )


@pytest.fixture
def merger() -> OntologyMerger:
    return OntologyMerger()


class TestEntityMerge:

    def test_extend_concatenates_properties(self, merger, base_ontology, domain_ontology):
        merged = merger.merge_definitions([base_ontology, domain_ontology])
        emp = merged.entities["Employee"]
        prop_names = emp.get_property_names()
        assert "name" in prop_names
        assert "email" in prop_names
        assert "project_code" in prop_names

    def test_extend_unions_vectorize(self, merger, base_ontology):
        ext = OntologyDefinition(
            name="ext",
            entities={
                "Employee": EntityDef(
                    extend=True,
                    properties=[{"title": PropertyDef(type="string")}],
                    vectorize=["title"],
                ),
            },
        )
        merged = merger.merge_definitions([base_ontology, ext])
        assert set(merged.entities["Employee"].vectorize) == {"name", "title"}

    def test_extend_overrides_source(self, merger, base_ontology):
        ext = OntologyDefinition(
            name="ext",
            entities={
                "Employee": EntityDef(
                    extend=True,
                    source="workday_api",
                ),
            },
        )
        merged = merger.merge_definitions([base_ontology, ext])
        assert merged.entities["Employee"].source == "workday_api"

    def test_no_extend_on_existing_raises(self, merger, base_ontology):
        dup = OntologyDefinition(
            name="dup",
            entities={
                "Employee": EntityDef(
                    collection="employees_v2",
                    # extend=False (default)
                ),
            },
        )
        with pytest.raises(OntologyMergeError, match="extend"):
            merger.merge_definitions([base_ontology, dup])

    def test_new_entity_added(self, merger, base_ontology, domain_ontology):
        merged = merger.merge_definitions([base_ontology, domain_ontology])
        assert "Project" in merged.entities
        assert merged.entities["Project"].collection == "projects"

    def test_immutable_key_field(self, merger, base_ontology):
        ext = OntologyDefinition(
            name="ext",
            entities={
                "Employee": EntityDef(
                    extend=True,
                    key_field="different_id",
                ),
            },
        )
        with pytest.raises(OntologyMergeError, match="key_field"):
            merger.merge_definitions([base_ontology, ext])

    def test_immutable_collection(self, merger, base_ontology):
        ext = OntologyDefinition(
            name="ext",
            entities={
                "Employee": EntityDef(
                    extend=True,
                    collection="different_collection",
                ),
            },
        )
        with pytest.raises(OntologyMergeError, match="collection"):
            merger.merge_definitions([base_ontology, ext])

    def test_property_name_collision_raises(self, merger, base_ontology):
        ext = OntologyDefinition(
            name="ext",
            entities={
                "Employee": EntityDef(
                    extend=True,
                    properties=[{"name": PropertyDef(type="string")}],  # already exists
                ),
            },
        )
        with pytest.raises(OntologyMergeError, match="already exists"):
            merger.merge_definitions([base_ontology, ext])


class TestRelationMerge:

    def test_new_relation_added(self, merger, base_ontology, domain_ontology):
        merged = merger.merge_definitions([base_ontology, domain_ontology])
        assert "assigned_to" in merged.relations
        assert merged.relations["assigned_to"].from_entity == "Employee"

    def test_concat_discovery_rules(self, merger, base_ontology):
        ext = OntologyDefinition(
            name="ext",
            relations={
                "belongs_to": RelationDef(
                    from_entity="Employee",
                    to_entity="Department",
                    edge_collection="belongs_to_dept",
                    discovery=DiscoveryConfig(
                        rules=[
                            DiscoveryRule(
                                source_field="dept_name",
                                target_field="name",
                                match_type="fuzzy",
                                threshold=0.80,
                            )
                        ]
                    ),
                ),
            },
        )
        merged = merger.merge_definitions([base_ontology, ext])
        rules = merged.relations["belongs_to"].discovery.rules
        assert len(rules) == 2  # original + extension
        assert rules[0].match_type == "exact"
        assert rules[1].match_type == "fuzzy"

    def test_immutable_endpoints(self, merger, base_ontology):
        ext = OntologyDefinition(
            name="ext",
            relations={
                "belongs_to": RelationDef(
                    from_entity="Department",  # changed!
                    to_entity="Employee",  # changed!
                    edge_collection="belongs_to_dept",
                ),
            },
        )
        with pytest.raises(OntologyMergeError, match="endpoints"):
            merger.merge_definitions([base_ontology, ext])

    def test_relation_unknown_entity_raises(self, merger, base_ontology):
        ext = OntologyDefinition(
            name="ext",
            relations={
                "bad_rel": RelationDef(
                    from_entity="Employee",
                    to_entity="Nonexistent",
                    edge_collection="bad_edge",
                ),
            },
        )
        with pytest.raises(OntologyMergeError, match="unknown entity"):
            merger.merge_definitions([base_ontology, ext])


class TestPatternMerge:

    def test_new_pattern_added(self, merger, base_ontology, domain_ontology):
        merged = merger.merge_definitions([base_ontology, domain_ontology])
        assert "find_project" in merged.traversal_patterns

    def test_concat_trigger_intents(self, merger, base_ontology, domain_ontology):
        merged = merger.merge_definitions([base_ontology, domain_ontology])
        intents = merged.traversal_patterns["find_dept"].trigger_intents
        assert "my department" in intents
        assert "which department" in intents

    def test_override_template(self, merger, base_ontology, domain_ontology):
        merged = merger.merge_definitions([base_ontology, domain_ontology])
        # Domain overrides the query template
        assert "v.name" in merged.traversal_patterns["find_dept"].query_template


class TestIntegrityValidation:

    def test_vectorize_invalid_field_raises(self, merger):
        bad = OntologyDefinition(
            name="bad",
            entities={
                "Employee": EntityDef(
                    collection="employees",
                    properties=[{"name": PropertyDef(type="string")}],
                    vectorize=["nonexistent_field"],
                ),
            },
        )
        with pytest.raises(OntologyIntegrityError, match="vectorize"):
            merger.merge_definitions([bad])

    def test_valid_ontology_passes(self, merger, base_ontology, domain_ontology):
        merged = merger.merge_definitions([base_ontology, domain_ontology])
        # Should not raise
        assert len(merged.layers) == 2


class TestMergedOntologyMetadata:

    def test_layers_tracked(self, merger, base_ontology, domain_ontology):
        merged = merger.merge_definitions([base_ontology, domain_ontology])
        assert merged.layers == ["base", "field_services"]
        assert merged.name == "field_services"

    def test_merge_timestamp(self, merger, base_ontology):
        merged = merger.merge_definitions([base_ontology])
        assert merged.merge_timestamp is not None
