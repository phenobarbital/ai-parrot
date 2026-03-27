"""Tests for ontology Pydantic schema models."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from parrot.knowledge.ontology.schema import (
    PropertyDef,
    EntityDef,
    DiscoveryRule,
    DiscoveryConfig,
    RelationDef,
    TraversalPattern,
    OntologyDefinition,
    MergedOntology,
    TenantContext,
    ResolvedIntent,
    EnrichedContext,
)


# ── PropertyDef ──


class TestPropertyDef:

    def test_valid_types(self):
        for t in ("string", "int", "float", "boolean", "date", "list", "dict"):
            p = PropertyDef(type=t)
            assert p.type == t

    def test_rejects_unknown_type(self):
        with pytest.raises(ValidationError):
            PropertyDef(type="unknown_type")

    def test_rejects_extra_fields(self):
        with pytest.raises(ValidationError):
            PropertyDef(type="string", bogus_field="x")

    def test_defaults(self):
        p = PropertyDef(type="string")
        assert p.required is False
        assert p.unique is False
        assert p.default is None
        assert p.enum is None


# ── EntityDef ──


class TestEntityDef:

    def test_basic(self):
        e = EntityDef(
            collection="employees",
            key_field="employee_id",
            properties=[{"name": PropertyDef(type="string")}],
            vectorize=["name"],
        )
        assert e.collection == "employees"
        assert e.get_property_names() == {"name"}

    def test_extend_flag(self):
        e = EntityDef(extend=True)
        assert e.extend is True

    def test_rejects_extra(self):
        with pytest.raises(ValidationError):
            EntityDef(unknown_field="x")


# ── DiscoveryRule ──


class TestDiscoveryRule:

    def test_valid_match_types(self):
        for mt in ("exact", "fuzzy", "ai_assisted", "composite"):
            r = DiscoveryRule(source_field="a", target_field="b", match_type=mt)
            assert r.match_type == mt

    def test_invalid_match_type(self):
        with pytest.raises(ValidationError):
            DiscoveryRule(source_field="a", target_field="b", match_type="invalid")

    def test_default_threshold(self):
        r = DiscoveryRule(source_field="a", target_field="b")
        assert r.threshold == 0.85


# ── RelationDef ──


class TestRelationDef:

    def test_alias_from_to(self):
        """Test that 'from' and 'to' YAML keys work via aliases."""
        r = RelationDef(**{
            "from": "Employee",
            "to": "Department",
            "edge_collection": "belongs_to",
        })
        assert r.from_entity == "Employee"
        assert r.to_entity == "Department"

    def test_populate_by_name(self):
        """Test that from_entity/to_entity also work directly."""
        r = RelationDef(
            from_entity="Employee",
            to_entity="Project",
            edge_collection="assigned_to",
        )
        assert r.from_entity == "Employee"

    def test_rejects_extra(self):
        with pytest.raises(ValidationError):
            RelationDef(
                from_entity="A", to_entity="B",
                edge_collection="e", bogus="x",
            )


# ── TraversalPattern ──


class TestTraversalPattern:

    def test_valid_post_actions(self):
        for pa in ("vector_search", "tool_call", "none"):
            p = TraversalPattern(
                description="test",
                query_template="FOR x IN c RETURN x",
                post_action=pa,
            )
            assert p.post_action == pa

    def test_invalid_post_action(self):
        with pytest.raises(ValidationError):
            TraversalPattern(
                description="test",
                query_template="FOR x IN c RETURN x",
                post_action="invalid",
            )

    def test_trigger_intents(self):
        p = TraversalPattern(
            description="find portal",
            query_template="FOR x IN c RETURN x",
            trigger_intents=["my portal", "what portal"],
        )
        assert len(p.trigger_intents) == 2


# ── OntologyDefinition ──


class TestOntologyDefinition:

    def test_basic(self):
        od = OntologyDefinition(name="base", version="1.0")
        assert od.name == "base"
        assert od.entities == {}
        assert od.relations == {}

    def test_with_entities_and_relations(self):
        od = OntologyDefinition(
            name="test",
            entities={
                "Employee": EntityDef(collection="employees", key_field="id"),
            },
            relations={
                "reports_to": RelationDef(
                    from_entity="Employee",
                    to_entity="Employee",
                    edge_collection="reports_to",
                ),
            },
        )
        assert "Employee" in od.entities
        assert "reports_to" in od.relations

    def test_rejects_extra(self):
        with pytest.raises(ValidationError):
            OntologyDefinition(name="x", bogus="y")


# ── MergedOntology ──


class TestMergedOntology:

    @pytest.fixture
    def merged(self) -> MergedOntology:
        return MergedOntology(
            name="test_merged",
            version="1.0",
            entities={
                "Employee": EntityDef(
                    collection="employees",
                    key_field="employee_id",
                    properties=[
                        {"name": PropertyDef(type="string")},
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
                ),
            },
            traversal_patterns={
                "find_dept": TraversalPattern(
                    description="Find employee department",
                    trigger_intents=["my department"],
                    query_template="FOR v IN 1..1 OUTBOUND @user_id belongs_to_dept RETURN v",
                ),
            },
            layers=["base.yaml", "domain.yaml"],
            merge_timestamp=datetime.now(timezone.utc),
        )

    def test_get_entity_collections(self, merged):
        cols = merged.get_entity_collections()
        assert set(cols) == {"employees", "departments"}

    def test_get_edge_collections(self, merged):
        cols = merged.get_edge_collections()
        assert cols == ["belongs_to_dept"]

    def test_get_vectorizable_fields(self, merged):
        assert merged.get_vectorizable_fields("Employee") == ["name"]
        assert merged.get_vectorizable_fields("Department") == []
        assert merged.get_vectorizable_fields("Nonexistent") == []

    def test_build_schema_prompt(self, merged):
        prompt = merged.build_schema_prompt()
        assert "Available ontology:" in prompt
        assert "Employee" in prompt
        assert "Department" in prompt
        assert "belongs_to" in prompt
        assert "find_dept" in prompt
        assert "my department" in prompt

    def test_layers_tracked(self, merged):
        assert merged.layers == ["base.yaml", "domain.yaml"]


# ── ResolvedIntent ──


class TestResolvedIntent:

    def test_graph_query(self):
        ri = ResolvedIntent(
            action="graph_query",
            pattern="find_portal",
            aql="FOR v IN 1..2 OUTBOUND @uid g RETURN v",
            source="fast_path",
        )
        assert ri.action == "graph_query"

    def test_vector_only(self):
        ri = ResolvedIntent(action="vector_only")
        assert ri.pattern is None
        assert ri.aql is None

    def test_invalid_action(self):
        with pytest.raises(ValidationError):
            ResolvedIntent(action="invalid")


# ── EnrichedContext ──


class TestEnrichedContext:

    def test_defaults(self):
        ec = EnrichedContext()
        assert ec.source == "none"
        assert ec.graph_context is None
        assert ec.tool_hint is None

    def test_cache_roundtrip(self):
        ec = EnrichedContext(
            source="ontology",
            graph_context=[{"name": "Alice", "dept": "eng"}],
            metadata={"tenant": "epson"},
        )
        cached = ec.to_cache()
        restored = EnrichedContext.from_cache(cached)
        assert restored.source == "ontology"
        assert restored.graph_context == [{"name": "Alice", "dept": "eng"}]
        assert restored.metadata == {"tenant": "epson"}

    def test_with_intent(self):
        intent = ResolvedIntent(action="graph_query", source="fast_path")
        ec = EnrichedContext(source="ontology", intent=intent)
        assert ec.intent.action == "graph_query"


# ── TenantContext ──


class TestTenantContext:

    def test_basic(self):
        merged = MergedOntology(
            name="test",
            version="1.0",
            entities={},
            relations={},
            traversal_patterns={},
            layers=["base.yaml"],
            merge_timestamp=datetime.now(timezone.utc),
        )
        ctx = TenantContext(
            tenant_id="epson",
            arango_db="epson_ontology",
            pgvector_schema="epson",
            ontology=merged,
        )
        assert ctx.tenant_id == "epson"
        assert ctx.arango_db == "epson_ontology"
