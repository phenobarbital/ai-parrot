"""Unit tests for parrot.knowledge.graphindex.persist."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, call, patch

from parrot.knowledge.graphindex.persist import GraphIndexPersistence, _node_to_doc, _edge_to_doc
from parrot.knowledge.graphindex.meta_ontology import KIND_TO_COLLECTION, EDGE_KIND_TO_COLLECTION
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)
from parrot.knowledge.ontology.schema import TenantContext, MergedOntology


def make_ctx(tenant_id: str = "test-tenant") -> TenantContext:
    """Create a minimal TenantContext for testing using model_construct to bypass validation."""
    # Use model_construct to avoid building a full MergedOntology in unit tests
    fake_ontology = MergedOntology.model_construct(
        name="test",
        version="1.0",
        entities={},
        relations={},
        traversal_patterns={},
        layers=[],
        merge_timestamp=None,
    )
    return TenantContext(
        tenant_id=tenant_id,
        arango_db=f"db_{tenant_id}",
        pgvector_schema=f"schema_{tenant_id}",
        ontology=fake_ontology,
    )


def make_node(
    node_id: str,
    kind: NodeKind = NodeKind.DOCUMENT,
    source_uri: str = "test.txt",
) -> UniversalNode:
    """Create a minimal UniversalNode for testing."""
    return UniversalNode(
        node_id=node_id,
        kind=kind,
        title=f"Node {node_id}",
        source_uri=source_uri,
    )


def make_edge(
    source_id: str,
    target_id: str,
    kind: EdgeKind = EdgeKind.CONTAINS,
) -> UniversalEdge:
    """Create a minimal UniversalEdge for testing."""
    return UniversalEdge(source_id=source_id, target_id=target_id, kind=kind)


def make_graph_store() -> MagicMock:
    """Create a mock OntologyGraphStore."""
    store = MagicMock()
    # UpsertResult-like object
    upsert_result = MagicMock()
    upsert_result.inserted = 1
    upsert_result.updated = 0
    store.upsert_nodes = AsyncMock(return_value=upsert_result)
    store.create_edges = AsyncMock(return_value=1)
    store.soft_delete_nodes = AsyncMock(return_value=1)
    store.get_all_nodes = AsyncMock(return_value=[])
    return store


class TestNodeToDoc:
    def test_includes_key(self):
        node = make_node("n1", NodeKind.SYMBOL)
        doc = _node_to_doc(node)
        assert doc["_key"] == "n1"
        assert doc["node_id"] == "n1"

    def test_includes_kind_value(self):
        node = make_node("n1", NodeKind.SKILL)
        doc = _node_to_doc(node)
        assert doc["kind"] == NodeKind.SKILL.value

    def test_includes_provenance_value(self):
        node = make_node("n1")
        doc = _node_to_doc(node)
        assert doc["provenance"] == Provenance.EXTRACTED.value


class TestEdgeToDoc:
    def test_includes_source_and_target(self):
        edge = make_edge("src", "tgt", EdgeKind.REFERENCES)
        node_kind_map = {"src": NodeKind.DOCUMENT.value, "tgt": NodeKind.SECTION.value}
        doc = _edge_to_doc(edge, KIND_TO_COLLECTION, node_kind_map)
        assert doc["source_id"] == "src"
        assert doc["target_id"] == "tgt"

    def test_includes_kind_value(self):
        edge = make_edge("src", "tgt", EdgeKind.DEFINES)
        node_kind_map = {"src": NodeKind.DOCUMENT.value, "tgt": NodeKind.SYMBOL.value}
        doc = _edge_to_doc(edge, KIND_TO_COLLECTION, node_kind_map)
        assert doc["kind"] == EdgeKind.DEFINES.value

    def test_includes_confidence(self):
        edge = UniversalEdge(
            source_id="a",
            target_id="b",
            kind=EdgeKind.MENTIONS,
            provenance=Provenance.INFERRED,
            confidence=0.9,
        )
        node_kind_map = {"a": NodeKind.DOCUMENT.value, "b": NodeKind.CONCEPT.value}
        doc = _edge_to_doc(edge, KIND_TO_COLLECTION, node_kind_map)
        assert doc["confidence"] == 0.9

    def test_from_and_to_are_fully_qualified(self):
        """_from and _to must be <collection>/<node_id> ArangoDB references."""
        edge = make_edge("node-abc", "node-xyz", EdgeKind.CONTAINS)
        node_kind_map = {
            "node-abc": NodeKind.DOCUMENT.value,
            "node-xyz": NodeKind.SECTION.value,
        }
        doc = _edge_to_doc(edge, KIND_TO_COLLECTION, node_kind_map)
        src_collection = KIND_TO_COLLECTION[NodeKind.DOCUMENT.value]
        tgt_collection = KIND_TO_COLLECTION[NodeKind.SECTION.value]
        assert doc["_from"] == f"{src_collection}/node-abc"
        assert doc["_to"] == f"{tgt_collection}/node-xyz"

    def test_unknown_node_kind_falls_back_to_bare_id(self):
        """When a node_id is absent from node_kind_map, _from/_to fall back to bare id."""
        edge = make_edge("unknown-src", "unknown-tgt", EdgeKind.EXPLAINS)
        doc = _edge_to_doc(edge, KIND_TO_COLLECTION, node_kind_map={})
        assert doc["_from"] == "unknown-src"
        assert doc["_to"] == "unknown-tgt"


class TestGraphIndexPersistence:
    @pytest.fixture
    def store(self):
        return make_graph_store()

    @pytest.fixture
    def persistence(self, store):
        return GraphIndexPersistence(graph_store=store)

    @pytest.fixture
    def ctx(self):
        return make_ctx()

    # ------------------------------------------------------------------
    # persist_graph
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_empty_nodes_no_op(self, persistence, store, ctx):
        """Empty node/edge lists should not call upsert or create_edges."""
        result = await persistence.persist_graph(ctx, [], [])
        store.upsert_nodes.assert_not_called()
        store.create_edges.assert_not_called()
        assert result["nodes_persisted"] == 0
        assert result["edges_persisted"] == 0

    @pytest.mark.asyncio
    async def test_nodes_routed_to_correct_collections(self, persistence, store, ctx):
        """Each NodeKind must route to its correct ArangoDB vertex collection."""
        nodes = [
            make_node("d1", NodeKind.DOCUMENT),
            make_node("s1", NodeKind.SECTION),
            make_node("sy1", NodeKind.SYMBOL),
            make_node("c1", NodeKind.CONCEPT),
            make_node("r1", NodeKind.RATIONALE),
            make_node("sk1", NodeKind.SKILL),
        ]
        await persistence.persist_graph(ctx, nodes, [])

        called_collections = {c.args[1] for c in store.upsert_nodes.call_args_list}
        expected = set(KIND_TO_COLLECTION.values())
        assert called_collections == expected

    @pytest.mark.asyncio
    async def test_edges_routed_to_correct_collections(self, persistence, store, ctx):
        """Each EdgeKind must route to its correct ArangoDB edge collection."""
        # Need nodes first (for persistence, edges go directly to create_edges)
        edges = [
            make_edge("a", "b", EdgeKind.CONTAINS),
            make_edge("a", "c", EdgeKind.REFERENCES),
            make_edge("a", "d", EdgeKind.DEFINES),
            make_edge("a", "e", EdgeKind.MENTIONS),
            make_edge("a", "f", EdgeKind.EXPLAINS),
            # FEAT-240 (TASK-1571): EXTENDS added for Odoo model inheritance
            make_edge("a", "g", EdgeKind.EXTENDS),
        ]
        # We only test edge routing; no nodes needed for this
        await persistence.persist_graph(ctx, [], edges)

        called_edge_collections = {c.args[1] for c in store.create_edges.call_args_list}
        expected = set(EDGE_KIND_TO_COLLECTION.values())
        assert called_edge_collections == expected

    @pytest.mark.asyncio
    async def test_persist_graph_returns_counts(self, persistence, store, ctx):
        """persist_graph returns nodes_persisted and edges_persisted."""
        upsert_result = MagicMock()
        upsert_result.inserted = 2
        upsert_result.updated = 1
        store.upsert_nodes = AsyncMock(return_value=upsert_result)
        store.create_edges = AsyncMock(return_value=1)

        nodes = [make_node("n1", NodeKind.DOCUMENT)]
        edges = [make_edge("n1", "n2", EdgeKind.CONTAINS)]
        result = await persistence.persist_graph(ctx, nodes, edges)

        assert "nodes_persisted" in result
        assert "edges_persisted" in result
        assert result["nodes_persisted"] >= 0
        assert result["edges_persisted"] >= 0

    @pytest.mark.asyncio
    async def test_upsert_nodes_called_with_key_field(self, persistence, store, ctx):
        """upsert_nodes must be called with key_field='node_id'."""
        nodes = [make_node("n1", NodeKind.DOCUMENT)]
        await persistence.persist_graph(ctx, nodes, [])

        assert store.upsert_nodes.call_count >= 1
        for c in store.upsert_nodes.call_args_list:
            assert c.kwargs.get("key_field") == "node_id" or c.args[-1] == "node_id"

    # ------------------------------------------------------------------
    # replace_document_slice
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_soft_delete_uses_key_not_key_field(self, store, ctx):
        """soft_delete_nodes must be called with _key values, not key_field strings."""
        existing_doc = {"_key": "old-node-1", "source_uri": "doc://test.txt", "node_id": "old-node-1"}
        store.get_all_nodes = AsyncMock(return_value=[existing_doc])

        persistence = GraphIndexPersistence(graph_store=store)
        nodes = [make_node("new-node-1", NodeKind.DOCUMENT, source_uri="doc://test.txt")]
        await persistence.replace_document_slice(ctx, "doc://test.txt", nodes, [])

        # soft_delete_nodes must have been called with _key values
        assert store.soft_delete_nodes.called
        call_args = store.soft_delete_nodes.call_args
        # The keys list (3rd arg) must contain the _key value "old-node-1"
        keys_arg = call_args.args[2] if len(call_args.args) >= 3 else call_args.kwargs.get("keys")
        assert "old-node-1" in keys_arg

    @pytest.mark.asyncio
    async def test_atomic_replace_sequence(self, store, ctx):
        """soft_delete must be called BEFORE upsert_nodes in replace_document_slice."""
        call_order: list[str] = []

        existing_doc = {"_key": "old-1", "source_uri": "doc://test.txt", "node_id": "old-1"}
        store.get_all_nodes = AsyncMock(return_value=[existing_doc])

        async def mock_soft_delete(*args, **kwargs):
            call_order.append("soft_delete")
            return 1

        async def mock_upsert(*args, **kwargs):
            call_order.append("upsert")
            r = MagicMock()
            r.inserted = 1
            r.updated = 0
            return r

        store.soft_delete_nodes = mock_soft_delete
        store.upsert_nodes = mock_upsert

        persistence = GraphIndexPersistence(graph_store=store)
        nodes = [make_node("new-1", NodeKind.DOCUMENT, source_uri="doc://test.txt")]
        await persistence.replace_document_slice(ctx, "doc://test.txt", nodes, [])

        # soft_delete must appear before upsert
        assert "soft_delete" in call_order
        assert "upsert" in call_order
        soft_pos = call_order.index("soft_delete")
        upsert_pos = call_order.index("upsert")
        assert soft_pos < upsert_pos

    @pytest.mark.asyncio
    async def test_replace_document_slice_returns_counts(self, store, ctx):
        """replace_document_slice returns nodes_replaced and edges_replaced."""
        store.get_all_nodes = AsyncMock(return_value=[])
        upsert_result = MagicMock()
        upsert_result.inserted = 1
        upsert_result.updated = 0
        store.upsert_nodes = AsyncMock(return_value=upsert_result)
        store.create_edges = AsyncMock(return_value=0)

        persistence = GraphIndexPersistence(graph_store=store)
        nodes = [make_node("n1", NodeKind.DOCUMENT, source_uri="doc://test.txt")]
        result = await persistence.replace_document_slice(ctx, "doc://test.txt", nodes, [])

        assert "nodes_replaced" in result
        assert "edges_replaced" in result

    @pytest.mark.asyncio
    async def test_no_old_nodes_skips_soft_delete(self, store, ctx):
        """If no existing nodes for document, soft_delete is not called."""
        store.get_all_nodes = AsyncMock(return_value=[])
        upsert_result = MagicMock()
        upsert_result.inserted = 1
        upsert_result.updated = 0
        store.upsert_nodes = AsyncMock(return_value=upsert_result)

        persistence = GraphIndexPersistence(graph_store=store)
        nodes = [make_node("n1", NodeKind.DOCUMENT, source_uri="doc://fresh.txt")]
        await persistence.replace_document_slice(ctx, "doc://fresh.txt", nodes, [])

        store.soft_delete_nodes.assert_not_called()

    @pytest.mark.asyncio
    async def test_tenant_locking_serializes_concurrent_calls(self, store, ctx):
        """Concurrent replace_document_slice calls for same tenant should serialize."""
        gate = asyncio.Event()
        call_log: list[str] = []

        store.get_all_nodes = AsyncMock(return_value=[])

        async def slow_upsert(*args, **kwargs):
            call_log.append("upsert_start")
            await asyncio.sleep(0)  # yield to allow other coroutines
            call_log.append("upsert_end")
            r = MagicMock()
            r.inserted = 1
            r.updated = 0
            return r

        store.upsert_nodes = slow_upsert

        persistence = GraphIndexPersistence(graph_store=store)
        nodes_a = [make_node("na", NodeKind.DOCUMENT, source_uri="doc://a.txt")]
        nodes_b = [make_node("nb", NodeKind.DOCUMENT, source_uri="doc://b.txt")]

        # Run both concurrently
        await asyncio.gather(
            persistence.replace_document_slice(ctx, "doc://a.txt", nodes_a, []),
            persistence.replace_document_slice(ctx, "doc://b.txt", nodes_b, []),
        )

        # The calls should be serialized: start-end-start-end, not interleaved start-start
        for i in range(len(call_log) - 1):
            if call_log[i] == "upsert_start":
                assert call_log[i + 1] == "upsert_end", (
                    f"Interleaved calls detected: {call_log}"
                )

    @pytest.mark.asyncio
    async def test_different_tenants_do_not_share_locks(self):
        """Two different tenants should have independent locks."""
        store = make_graph_store()
        persistence = GraphIndexPersistence(graph_store=store)

        ctx_a = make_ctx("tenant-alpha")
        ctx_b = make_ctx("tenant-beta")

        nodes_a = [make_node("na", NodeKind.DOCUMENT)]
        nodes_b = [make_node("nb", NodeKind.DOCUMENT)]

        # Both should complete without deadlock
        await asyncio.gather(
            persistence.replace_document_slice(ctx_a, "doc://a.txt", nodes_a, []),
            persistence.replace_document_slice(ctx_b, "doc://b.txt", nodes_b, []),
        )

        assert store.upsert_nodes.call_count >= 2

    @pytest.mark.asyncio
    async def test_unknown_node_kind_skipped(self, store, ctx):
        """Nodes with unrecognised kind are logged and skipped gracefully."""
        # Create a node then patch KIND_TO_COLLECTION to not include its kind
        node = make_node("n1", NodeKind.DOCUMENT)
        with patch(
            "parrot.knowledge.graphindex.persist.KIND_TO_COLLECTION", {}
        ):
            persistence = GraphIndexPersistence(graph_store=store)
            result = await persistence.persist_graph(ctx, [node], [])
            # Should not raise; upsert_nodes never called since mapping is empty
            assert result["nodes_persisted"] == 0

    @pytest.mark.asyncio
    async def test_unknown_edge_kind_skipped(self, store, ctx):
        """Edges with unrecognised kind are logged and skipped gracefully."""
        edge = make_edge("a", "b", EdgeKind.CONTAINS)
        with patch(
            "parrot.knowledge.graphindex.persist.EDGE_KIND_TO_COLLECTION", {}
        ):
            persistence = GraphIndexPersistence(graph_store=store)
            result = await persistence.persist_graph(ctx, [], [edge])
            assert result["edges_persisted"] == 0
