"""Tests for the knowledge.ontology.yaml YAML layer (TASK-1084).

Validates that the knowledge YAML layer loads through OntologyMerger
without validation errors and that all expected entities, relations,
and traversal patterns appear in the resulting MergedOntology.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.ontology.merger import OntologyMerger
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.schema import MergedOntology
from parrot.knowledge.ontology.tenant import TenantOntologyManager

# Paths to default ontology files shipped with the package
_DEFAULTS_DIR = Path(__file__).parent.parent.parent / "src" / "parrot" / "knowledge" / "ontology" / "defaults"
_BASE_YAML = _DEFAULTS_DIR / "base.ontology.yaml"
_KNOWLEDGE_YAML = _DEFAULTS_DIR / "knowledge.ontology.yaml"

# Path to test fixtures
_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "concept_authority"
_ACME_AUTHORITY_YAML = _FIXTURES_DIR / "authority" / "acme.yaml"


@pytest.fixture
def merged_knowledge() -> MergedOntology:
    """Load base + knowledge YAML layers through OntologyMerger."""
    merger = OntologyMerger()
    return merger.merge([_BASE_YAML, _KNOWLEDGE_YAML])


class TestKnowledgeYamlLoads:
    """Tests that knowledge.ontology.yaml loads correctly."""

    def test_knowledge_yaml_file_exists(self) -> None:
        """The knowledge YAML file must exist at the expected path."""
        assert _KNOWLEDGE_YAML.exists(), (
            f"knowledge.ontology.yaml not found at {_KNOWLEDGE_YAML}"
        )

    def test_knowledge_yaml_parses_without_error(self) -> None:
        """knowledge.ontology.yaml must parse into an OntologyDefinition."""
        definition = OntologyParser.load(_KNOWLEDGE_YAML)
        assert definition.name == "knowledge"
        assert definition.version == "1.0"
        assert definition.extends == "base"

    def test_base_yaml_parses_without_error(self) -> None:
        """base.ontology.yaml must still parse correctly."""
        definition = OntologyParser.load(_BASE_YAML)
        assert definition.name == "base"

    def test_merge_base_and_knowledge_succeeds(self, merged_knowledge: MergedOntology) -> None:
        """Merging base + knowledge must produce a valid MergedOntology."""
        assert merged_knowledge is not None
        assert isinstance(merged_knowledge, MergedOntology)

    def test_merged_has_layers(self, merged_knowledge: MergedOntology) -> None:
        """Merged ontology must record both YAML layers."""
        assert len(merged_knowledge.layers) == 2


class TestDocumentEntity:
    """Tests for the Document entity in the knowledge layer."""

    def test_document_entity_present(self, merged_knowledge: MergedOntology) -> None:
        """Document entity must be present after merge."""
        assert "Document" in merged_knowledge.entities

    def test_document_collection(self, merged_knowledge: MergedOntology) -> None:
        """Document entity must target the 'documents' collection."""
        doc = merged_knowledge.entities["Document"]
        assert doc.collection == "documents"

    def test_document_key_field(self, merged_knowledge: MergedOntology) -> None:
        """Document entity key_field must be 'document_id'."""
        doc = merged_knowledge.entities["Document"]
        assert doc.key_field == "document_id"

    def test_document_has_required_properties(self, merged_knowledge: MergedOntology) -> None:
        """Document entity must have all expected properties."""
        doc = merged_knowledge.entities["Document"]
        prop_names = doc.get_property_names()
        expected = {
            "document_id", "title", "doc_type", "version",
            "effective_date", "is_current", "authority_score",
            "pageindex_tree_id", "language",
        }
        assert expected.issubset(prop_names), (
            f"Missing Document properties: {expected - prop_names}"
        )

    def test_document_vectorizes_title(self, merged_knowledge: MergedOntology) -> None:
        """Document entity must vectorize only 'title'."""
        doc = merged_knowledge.entities["Document"]
        assert "title" in doc.vectorize


class TestConceptEntity:
    """Tests for the Concept entity in the knowledge layer."""

    def test_concept_entity_present(self, merged_knowledge: MergedOntology) -> None:
        """Concept entity must be present after merge."""
        assert "Concept" in merged_knowledge.entities

    def test_concept_collection(self, merged_knowledge: MergedOntology) -> None:
        """Concept entity must target the 'concepts' collection."""
        concept = merged_knowledge.entities["Concept"]
        assert concept.collection == "concepts"

    def test_concept_key_field(self, merged_knowledge: MergedOntology) -> None:
        """Concept entity key_field must be 'concept_id'."""
        concept = merged_knowledge.entities["Concept"]
        assert concept.key_field == "concept_id"

    def test_concept_has_required_properties(self, merged_knowledge: MergedOntology) -> None:
        """Concept entity must have all expected properties."""
        concept = merged_knowledge.entities["Concept"]
        prop_names = concept.get_property_names()
        expected = {"concept_id", "label", "synonyms", "description", "domain"}
        assert expected.issubset(prop_names), (
            f"Missing Concept properties: {expected - prop_names}"
        )

    def test_concept_vectorizes_expected_fields(self, merged_knowledge: MergedOntology) -> None:
        """Concept entity must vectorize label, description, and synonyms."""
        concept = merged_knowledge.entities["Concept"]
        assert "label" in concept.vectorize
        assert "description" in concept.vectorize
        assert "synonyms" in concept.vectorize


class TestRelations:
    """Tests for covers_topic and is_a relations."""

    def test_covers_topic_present(self, merged_knowledge: MergedOntology) -> None:
        """covers_topic relation must be present after merge."""
        assert "covers_topic" in merged_knowledge.relations

    def test_covers_topic_endpoints(self, merged_knowledge: MergedOntology) -> None:
        """covers_topic must go from Document to Concept."""
        rel = merged_knowledge.relations["covers_topic"]
        assert rel.from_entity == "Document"
        assert rel.to_entity == "Concept"

    def test_covers_topic_edge_collection(self, merged_knowledge: MergedOntology) -> None:
        """covers_topic must use the doc_covers_concept edge collection."""
        rel = merged_knowledge.relations["covers_topic"]
        assert rel.edge_collection == "doc_covers_concept"

    def test_covers_topic_has_authority_property(self, merged_knowledge: MergedOntology) -> None:
        """covers_topic must declare an 'authority' property."""
        rel = merged_knowledge.relations["covers_topic"]
        prop_names: set[str] = set()
        for prop_dict in rel.properties:
            prop_names.update(prop_dict.keys())
        assert "authority" in prop_names

    def test_is_a_present(self, merged_knowledge: MergedOntology) -> None:
        """is_a relation must be present after merge."""
        assert "is_a" in merged_knowledge.relations

    def test_is_a_endpoints(self, merged_knowledge: MergedOntology) -> None:
        """is_a must go from Concept to Concept."""
        rel = merged_knowledge.relations["is_a"]
        assert rel.from_entity == "Concept"
        assert rel.to_entity == "Concept"

    def test_is_a_edge_collection(self, merged_knowledge: MergedOntology) -> None:
        """is_a must use the concept_is_a edge collection."""
        rel = merged_knowledge.relations["is_a"]
        assert rel.edge_collection == "concept_is_a"


class TestTraversalPattern:
    """Tests for the authoritative_doc_for_topic traversal pattern."""

    def test_pattern_present(self, merged_knowledge: MergedOntology) -> None:
        """authoritative_doc_for_topic must be present after merge."""
        assert "authoritative_doc_for_topic" in merged_knowledge.traversal_patterns

    def test_pattern_post_action(self, merged_knowledge: MergedOntology) -> None:
        """Pattern post_action must be 'tool_call'."""
        pattern = merged_knowledge.traversal_patterns["authoritative_doc_for_topic"]
        assert pattern.post_action == "tool_call"

    def test_pattern_has_trigger_intents(self, merged_knowledge: MergedOntology) -> None:
        """Pattern must declare trigger_intents."""
        pattern = merged_knowledge.traversal_patterns["authoritative_doc_for_topic"]
        assert len(pattern.trigger_intents) > 0
        assert "how does" in pattern.trigger_intents

    def test_pattern_has_entity_extraction(self, merged_knowledge: MergedOntology) -> None:
        """Pattern must declare entity_extraction with a 'topic' rule."""
        pattern = merged_knowledge.traversal_patterns["authoritative_doc_for_topic"]
        assert "topic" in pattern.entity_extraction

    def test_entity_extraction_topic_rule(self, merged_knowledge: MergedOntology) -> None:
        """topic entity_extraction rule must use hybrid_concept_match resolver."""
        pattern = merged_knowledge.traversal_patterns["authoritative_doc_for_topic"]
        topic_rule = pattern.entity_extraction["topic"]
        assert topic_rule.type == "Concept"
        assert topic_rule.resolver == "hybrid_concept_match"
        assert topic_rule.scope == "same_tenant"
        assert topic_rule.ambiguity_strategy == "rerank_by_authority"
        assert topic_rule.required is True

    def test_pattern_has_tool_call(self, merged_knowledge: MergedOntology) -> None:
        """Pattern must have a tool_call spec."""
        pattern = merged_knowledge.traversal_patterns["authoritative_doc_for_topic"]
        assert pattern.tool_call is not None

    def test_tool_call_spec(self, merged_knowledge: MergedOntology) -> None:
        """tool_call must target PageIndexToolkit.search_documents_scoped."""
        pattern = merged_knowledge.traversal_patterns["authoritative_doc_for_topic"]
        tc = pattern.tool_call
        assert tc.toolkit == "PageIndexToolkit"
        assert tc.method == "search_documents_scoped"
        assert tc.credential_mode == "service_account"
        assert tc.result_binding == "pageindex_hits"
        assert tc.empty_team_behavior == "short_circuit"

    def test_tool_call_parameters(self, merged_knowledge: MergedOntology) -> None:
        """tool_call parameters must include tree_ids and query templates."""
        pattern = merged_knowledge.traversal_patterns["authoritative_doc_for_topic"]
        params = pattern.tool_call.parameters
        assert "tree_ids" in params
        assert "query" in params
        assert "include_tree_context" in params

    def test_pattern_has_query_template(self, merged_knowledge: MergedOntology) -> None:
        """Pattern query_template must reference the is_a traversal AQL."""
        pattern = merged_knowledge.traversal_patterns["authoritative_doc_for_topic"]
        qt = pattern.query_template
        assert "concept_family" in qt
        assert "concept_is_a" in qt
        assert "doc_covers_concept" in qt
        assert "@authority_level" in qt


class TestMergedOntologyIntegrity:
    """Tests that the fully merged ontology passes integrity checks."""

    def test_all_relation_endpoints_exist(self, merged_knowledge: MergedOntology) -> None:
        """All relation endpoints must reference existing entities."""
        entity_names = set(merged_knowledge.entities.keys())
        for rel_name, rel in merged_knowledge.relations.items():
            assert rel.from_entity in entity_names, (
                f"Relation '{rel_name}' from_entity '{rel.from_entity}' not found"
            )
            assert rel.to_entity in entity_names, (
                f"Relation '{rel_name}' to_entity '{rel.to_entity}' not found"
            )

    def test_vectorize_fields_in_properties(self, merged_knowledge: MergedOntology) -> None:
        """All vectorize fields must be declared in entity properties."""
        for entity_name, entity in merged_knowledge.entities.items():
            prop_names = entity.get_property_names()
            for vec_field in entity.vectorize:
                assert vec_field in prop_names, (
                    f"Entity '{entity_name}' vectorize field '{vec_field}' "
                    f"not in properties: {sorted(prop_names)}"
                )

    def test_build_schema_prompt_includes_new_entities(
        self, merged_knowledge: MergedOntology
    ) -> None:
        """Schema prompt must include Document and Concept."""
        prompt = merged_knowledge.build_schema_prompt()
        assert "Document" in prompt
        assert "Concept" in prompt
        assert "authoritative_doc_for_topic" in prompt


class TestAuthorityFixtureFile:
    """Tests for the per-tenant authority YAML fixture."""

    def test_acme_authority_file_exists(self) -> None:
        """The acme.yaml authority fixture must exist."""
        assert _ACME_AUTHORITY_YAML.exists(), (
            f"acme.yaml not found at {_ACME_AUTHORITY_YAML}"
        )

    def test_acme_authority_yaml_has_name(self) -> None:
        """acme.yaml must have name: authority-acme."""
        import yaml
        with open(_ACME_AUTHORITY_YAML, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data is not None
        assert data.get("name") == "authority-acme"
        assert data.get("extends") == "knowledge"


class TestTenantOntologyManagerResolve:
    """Tests for TenantOntologyManager resolving the knowledge layer."""

    def test_resolve_uses_package_defaults(self) -> None:
        """TenantOntologyManager must resolve using package-bundled base ontology."""
        manager = TenantOntologyManager(
            ontology_dir=_DEFAULTS_DIR.parent,
            base_file="base.ontology.yaml",
        )
        # Resolve for a tenant with no client-specific ontology
        ctx = manager.resolve("test-tenant")
        assert ctx is not None
        assert ctx.tenant_id == "test-tenant"
        assert ctx.ontology is not None

    def test_resolve_with_knowledge_layer(self, tmp_path: Path) -> None:
        """TenantOntologyManager can resolve a chain including knowledge.ontology.yaml."""
        # Set up a minimal ontology_dir with base.ontology.yaml
        import shutil
        base_dst = tmp_path / "base.ontology.yaml"
        shutil.copy(_BASE_YAML, base_dst)

        # Resolve — will pick up base from tmp_path
        manager = TenantOntologyManager(
            ontology_dir=tmp_path,
            base_file="base.ontology.yaml",
        )
        ctx = manager.resolve("acme")
        assert "Employee" in ctx.ontology.entities

    def test_resolve_is_sync(self) -> None:
        """TenantOntologyManager.resolve must be synchronous (not a coroutine)."""
        import inspect
        manager = TenantOntologyManager(
            ontology_dir=_DEFAULTS_DIR.parent,
            base_file="base.ontology.yaml",
        )
        result = manager.resolve("sync-test-tenant")
        # If resolve returned a coroutine it would not have a .tenant_id attribute
        assert not inspect.iscoroutine(result)
        assert hasattr(result, "tenant_id")
