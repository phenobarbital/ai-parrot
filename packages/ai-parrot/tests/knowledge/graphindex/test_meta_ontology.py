"""Unit tests for parrot.knowledge.graphindex.meta_ontology."""

import pytest

from parrot.knowledge.graphindex.meta_ontology import (
    EDGE_KIND_TO_COLLECTION,
    KIND_TO_COLLECTION,
    build_graphindex_ontology,
)
from parrot.knowledge.ontology.schema import MergedOntology


class TestBuildGraphIndexOntology:
    def test_returns_merged_ontology(self):
        onto = build_graphindex_ontology()
        assert isinstance(onto, MergedOntology)

    def test_six_entity_types(self):
        onto = build_graphindex_ontology()
        assert len(onto.entities) == 6
        expected = {"document", "section", "symbol", "concept", "rationale", "skill"}
        assert set(onto.entities.keys()) == expected

    def test_five_relation_types(self):
        onto = build_graphindex_ontology()
        assert len(onto.relations) == 5
        expected = {"contains", "references", "defines", "mentions", "explains"}
        assert set(onto.relations.keys()) == expected

    def test_entity_collections_prefixed_gi(self):
        onto = build_graphindex_ontology()
        for entity_def in onto.entities.values():
            assert entity_def.collection is not None
            assert entity_def.collection.startswith("gi_"), (
                f"Collection {entity_def.collection} should start with 'gi_'"
            )

    def test_edge_collections_prefixed_gi(self):
        onto = build_graphindex_ontology()
        for rel_def in onto.relations.values():
            assert rel_def.edge_collection.startswith("gi_"), (
                f"Edge collection {rel_def.edge_collection} should start with 'gi_'"
            )

    def test_entity_key_field_node_id(self):
        onto = build_graphindex_ontology()
        for name, entity_def in onto.entities.items():
            assert entity_def.key_field == "node_id", (
                f"Entity {name} should have key_field='node_id'"
            )

    def test_vectorize_fields_present(self):
        onto = build_graphindex_ontology()
        for name, entity_def in onto.entities.items():
            assert "title" in entity_def.vectorize, (
                f"Entity {name} should vectorize 'title'"
            )

    def test_name_and_version(self):
        onto = build_graphindex_ontology()
        assert onto.name == "graphindex-meta-ontology"
        assert onto.version == "1.0"

    def test_get_entity_collections(self):
        onto = build_graphindex_ontology()
        collections = onto.get_entity_collections()
        assert len(collections) == 6
        for c in collections:
            assert c.startswith("gi_")

    def test_get_edge_collections(self):
        onto = build_graphindex_ontology()
        edge_collections = onto.get_edge_collections()
        assert len(edge_collections) == 5


class TestMappingDicts:
    def test_kind_to_collection_has_six_entries(self):
        assert len(KIND_TO_COLLECTION) == 6

    def test_edge_kind_to_collection_has_five_entries(self):
        assert len(EDGE_KIND_TO_COLLECTION) == 5

    def test_round_trip_document(self):
        from parrot.knowledge.graphindex.meta_ontology import COLLECTION_TO_KIND
        assert KIND_TO_COLLECTION["document"] == "gi_documents"
        assert COLLECTION_TO_KIND["gi_documents"] == "document"

    def test_mentions_edge_collection(self):
        assert EDGE_KIND_TO_COLLECTION["mentions"] == "gi_mentions"
