"""Unit tests for parrot.knowledge.graphindex.meta_ontology."""

import logging

import pytest

from parrot.knowledge.graphindex.meta_ontology import (
    COLLECTION_TO_KIND,
    EDGE_KIND_TO_COLLECTION,
    KIND_TO_COLLECTION,
    build_graphindex_ontology,
)
from parrot.knowledge.graphindex.schema import EdgeKind, NodeKind
from parrot.knowledge.ontology.schema import MergedOntology


class TestBuildGraphIndexOntology:
    def test_returns_merged_ontology(self):
        onto = build_graphindex_ontology()
        assert isinstance(onto, MergedOntology)

    def test_nine_entity_types(self):
        # FEAT-377 (TASK-1909) added wiki_page/run/claim (agent graph memory).
        onto = build_graphindex_ontology()
        assert len(onto.entities) == 9
        expected = {
            "document", "section", "symbol", "concept", "rationale", "skill",
            "wiki_page", "run", "claim",
        }
        assert set(onto.entities.keys()) == expected

    def test_ten_relation_types(self):
        # FEAT-240 (TASK-1571) added "extends" for Odoo model inheritance.
        # FEAT-377 (TASK-1909) added produced/about/supported_by/contradicts
        # (agent-assertion edges).
        onto = build_graphindex_ontology()
        assert len(onto.relations) == 10
        expected = {
            "contains", "references", "defines", "mentions", "explains", "extends",
            "produced", "about", "supported_by", "contradicts",
        }
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
        assert len(collections) == 9
        for c in collections:
            assert c.startswith("gi_")

    def test_get_edge_collections(self):
        onto = build_graphindex_ontology()
        edge_collections = onto.get_edge_collections()
        # FEAT-240 (TASK-1571) added gi_extends; FEAT-377 (TASK-1909) added
        # gi_produced/gi_about/gi_supported_by/gi_contradicts.
        assert len(edge_collections) == 10


class TestMappingDicts:
    def test_kind_to_collection_has_nine_entries(self):
        assert len(KIND_TO_COLLECTION) == 9

    def test_edge_kind_to_collection_has_ten_entries(self):
        # FEAT-240 (TASK-1571) added "extends" → "gi_extends"; FEAT-377
        # (TASK-1909) added the four agent-assertion edge kinds.
        assert len(EDGE_KIND_TO_COLLECTION) == 10

    def test_round_trip_document(self):
        assert KIND_TO_COLLECTION["document"] == "gi_documents"
        assert COLLECTION_TO_KIND["gi_documents"] == "document"

    def test_mentions_edge_collection(self):
        assert EDGE_KIND_TO_COLLECTION["mentions"] == "gi_mentions"

    def test_round_trip_memory_kinds(self):
        """FEAT-377 TASK-1909: wiki_page/run/claim round-trip."""
        for kind, collection in (
            ("wiki_page", "gi_wiki_pages"),
            ("run", "gi_runs"),
            ("claim", "gi_claims"),
        ):
            assert KIND_TO_COLLECTION[kind] == collection
            assert COLLECTION_TO_KIND[collection] == kind

    def test_assertion_edge_collections(self):
        """FEAT-377 TASK-1909: produced/about/supported_by/contradicts."""
        assert EDGE_KIND_TO_COLLECTION["produced"] == "gi_produced"
        assert EDGE_KIND_TO_COLLECTION["about"] == "gi_about"
        assert EDGE_KIND_TO_COLLECTION["supported_by"] == "gi_supported_by"
        assert EDGE_KIND_TO_COLLECTION["contradicts"] == "gi_contradicts"


class TestEnumCompleteness:
    """FEAT-377 TASK-1909: regression guard — new NodeKind/EdgeKind members
    must never silently fall through persistence routing again."""

    @pytest.mark.parametrize("kind", list(NodeKind))
    def test_every_node_kind_has_collection(self, kind: NodeKind):
        assert kind.value in KIND_TO_COLLECTION, (
            f"NodeKind.{kind.name} ({kind.value!r}) has no KIND_TO_COLLECTION entry"
        )

    @pytest.mark.parametrize("kind", list(EdgeKind))
    def test_every_edge_kind_has_collection(self, kind: EdgeKind):
        assert kind.value in EDGE_KIND_TO_COLLECTION, (
            f"EdgeKind.{kind.name} ({kind.value!r}) has no EDGE_KIND_TO_COLLECTION entry"
        )


class TestPersistenceRoutesMemoryKinds:
    """FEAT-377 TASK-1909: run/claim/wiki_page nodes no longer drop with
    an 'Unknown kind' warning in `_upsert_nodes`."""

    @pytest.mark.asyncio
    async def test_upsert_routes_memory_kinds_without_warning(self, caplog):
        from unittest.mock import AsyncMock, MagicMock

        from parrot.knowledge.graphindex.persist import GraphIndexPersistence
        from parrot.knowledge.graphindex.schema import Provenance, UniversalNode

        store = MagicMock()
        store.upsert_nodes = AsyncMock(
            return_value=MagicMock(inserted=1, updated=0)
        )
        persistence = GraphIndexPersistence(graph_store=store)
        nodes = [
            UniversalNode(
                node_id="run-1", kind=NodeKind.RUN, title="Run 1",
                source_uri="dev_loop://run-1", provenance=Provenance.ASSERTED,
            ),
            UniversalNode(
                node_id="claim-1", kind=NodeKind.CLAIM, title="Claim 1",
                source_uri="dev_loop://run-1", provenance=Provenance.ASSERTED,
            ),
            UniversalNode(
                node_id="wiki-1", kind=NodeKind.WIKI_PAGE, title="Wiki 1",
                source_uri="wiki://wiki-1", provenance=Provenance.ASSERTED,
            ),
        ]
        ctx = MagicMock()
        with caplog.at_level(logging.WARNING):
            total = await persistence._upsert_nodes(ctx, nodes)
        assert total == 3
        assert not any("Unknown kind" in rec.message for rec in caplog.records)
