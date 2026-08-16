"""Tests for ontology graph store with mocked ArangoDB client."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.knowledge.ontology.graph_store import OntologyGraphStore, UpsertResult
from parrot.knowledge.ontology.schema import (
    DiscoveryConfig,
    EntityDef,
    MergedOntology,
    PropertyDef,
    RelationDef,
    TenantContext,
    TraversalPattern,
)


@pytest.fixture
def mock_db():
    """Create a mock ArangoDB client."""
    db = AsyncMock()
    db.use = AsyncMock()
    db.create_database = AsyncMock()
    db.collection_exists = AsyncMock(return_value=False)
    db.create_collection = AsyncMock()
    db.graph_exists = AsyncMock(return_value=False)
    db.create_graph = AsyncMock()
    db.execute_query = AsyncMock(return_value=[])
    return db


@pytest.fixture
def tenant_ctx() -> TenantContext:
    """Create a test tenant context."""
    return TenantContext(
        tenant_id="test_tenant",
        arango_db="test_tenant_ontology",
        pgvector_schema="test_tenant",
        ontology=MergedOntology(
            name="test",
            version="1.0",
            entities={
                "Employee": EntityDef(
                    collection="employees",
                    key_field="employee_id",
                    properties=[
                        {"employee_id": PropertyDef(type="string")},
                        {"name": PropertyDef(type="string")},
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
            traversal_patterns={},
            layers=["test"],
            merge_timestamp=datetime.now(timezone.utc),
        ),
    )


@pytest.fixture
def store(mock_db) -> OntologyGraphStore:
    """Create a graph store with mocked client."""
    return OntologyGraphStore(arango_client=mock_db)


class TestInitializeTenant:

    @pytest.mark.asyncio
    async def test_creates_database(self, store, tenant_ctx, mock_db):
        await store.initialize_tenant(tenant_ctx)
        mock_db.create_database.assert_called_once_with("test_tenant_ontology")

    @pytest.mark.asyncio
    async def test_creates_vertex_collections(self, store, tenant_ctx, mock_db):
        await store.initialize_tenant(tenant_ctx)
        # Should create employees and departments
        collection_calls = [
            c.args[0] for c in mock_db.create_collection.call_args_list
            if len(c.args) > 0 and not c.kwargs.get("edge", False)
        ]
        assert "employees" in collection_calls
        assert "departments" in collection_calls

    @pytest.mark.asyncio
    async def test_creates_edge_collections(self, store, tenant_ctx, mock_db):
        await store.initialize_tenant(tenant_ctx)
        edge_calls = [
            c for c in mock_db.create_collection.call_args_list
            if c.kwargs.get("edge", False)
        ]
        assert len(edge_calls) >= 1

    @pytest.mark.asyncio
    async def test_creates_named_graph(self, store, tenant_ctx, mock_db):
        await store.initialize_tenant(tenant_ctx)
        mock_db.create_graph.assert_called_once()

    @pytest.mark.asyncio
    async def test_idempotent(self, store, tenant_ctx, mock_db):
        """Second call should not raise even if things exist."""
        mock_db.create_database.side_effect = Exception("already exists")
        mock_db.collection_exists.return_value = True
        mock_db.graph_exists.return_value = True
        # Should not raise
        await store.initialize_tenant(tenant_ctx)

    @pytest.mark.asyncio
    async def test_no_client_raises(self, tenant_ctx):
        store = OntologyGraphStore(arango_client=None)
        with pytest.raises(RuntimeError, match="requires an ArangoDB client"):
            await store.initialize_tenant(tenant_ctx)


class TestExecuteTraversal:

    @pytest.mark.asyncio
    async def test_returns_results(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = [
            {"name": "Alice", "dept": "eng"},
            {"name": "Bob", "dept": "sales"},
        ]
        results = await store.execute_traversal(
            tenant_ctx,
            aql="FOR v IN 1..1 OUTBOUND @uid belongs_to_dept RETURN v",
            bind_vars={"uid": "employees/emp_001"},
        )
        assert len(results) == 2
        assert results[0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_merges_collection_binds(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = []
        await store.execute_traversal(
            tenant_ctx,
            aql="FOR v IN @@col RETURN v",
            bind_vars={"limit": 10},
            collection_binds={"@col": "employees"},
        )
        call_binds = mock_db.execute_query.call_args.kwargs.get("bind_vars", {})
        assert "@col" in call_binds
        assert "limit" in call_binds

    @pytest.mark.asyncio
    async def test_empty_result(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = None
        results = await store.execute_traversal(
            tenant_ctx, aql="FOR v IN c RETURN v",
        )
        assert results == []


class TestUpsertNodes:

    @pytest.mark.asyncio
    async def test_returns_upsert_result(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = [
            {"type": "inserted"},
            {"type": "updated"},
            {"type": "unchanged"},
        ]
        result = await store.upsert_nodes(
            tenant_ctx, "employees",
            nodes=[
                {"employee_id": "1", "name": "Alice"},
                {"employee_id": "2", "name": "Bob"},
                {"employee_id": "3", "name": "Carol"},
            ],
            key_field="employee_id",
        )
        assert isinstance(result, UpsertResult)
        assert result.inserted == 1
        assert result.updated == 1
        assert result.unchanged == 1

    @pytest.mark.asyncio
    async def test_empty_nodes(self, store, tenant_ctx, mock_db):
        result = await store.upsert_nodes(
            tenant_ctx, "employees", nodes=[], key_field="employee_id",
        )
        assert result.inserted == 0
        mock_db.execute_query.assert_not_called()


class TestCreateEdges:

    @pytest.mark.asyncio
    async def test_creates_edges(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = [1, 1, 0]
        count = await store.create_edges(
            tenant_ctx, "belongs_to_dept",
            edges=[
                {"_from": "employees/1", "_to": "departments/eng"},
                {"_from": "employees/2", "_to": "departments/sales"},
                {"_from": "employees/1", "_to": "departments/eng"},  # dup
            ],
        )
        assert count == 2  # 2 of 3 returned truthy

    @pytest.mark.asyncio
    async def test_empty_edges(self, store, tenant_ctx, mock_db):
        count = await store.create_edges(
            tenant_ctx, "belongs_to_dept", edges=[],
        )
        assert count == 0
        mock_db.execute_query.assert_not_called()


class TestGetAllNodes:

    @pytest.mark.asyncio
    async def test_returns_active_nodes(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = [
            {"_key": "1", "name": "Alice", "_active": True},
            {"_key": "2", "name": "Bob", "_active": True},
        ]
        nodes = await store.get_all_nodes(tenant_ctx, "employees")
        assert len(nodes) == 2

    @pytest.mark.asyncio
    async def test_empty_collection(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = []
        nodes = await store.get_all_nodes(tenant_ctx, "employees")
        assert nodes == []


class TestSoftDeleteNodes:

    @pytest.mark.asyncio
    async def test_soft_deletes(self, store, tenant_ctx, mock_db):
        await store.soft_delete_nodes(
            tenant_ctx, "employees", keys=["1", "2"],
        )
        mock_db.execute_query.assert_called_once()
        call_binds = mock_db.execute_query.call_args.kwargs.get("bind_vars", {})
        assert call_binds["keys"] == ["1", "2"]

    @pytest.mark.asyncio
    async def test_empty_keys_noop(self, store, tenant_ctx, mock_db):
        await store.soft_delete_nodes(
            tenant_ctx, "employees", keys=[],
        )
        mock_db.execute_query.assert_not_called()


class TestEnsureCollection:

    @pytest.mark.asyncio
    async def test_creates_when_missing(self, store, tenant_ctx, mock_db):
        mock_db.collection_exists.return_value = False
        await store.ensure_collection(tenant_ctx, "gi_commits")
        mock_db.create_collection.assert_called_once_with("gi_commits")

    @pytest.mark.asyncio
    async def test_creates_edge_collection(self, store, tenant_ctx, mock_db):
        mock_db.collection_exists.return_value = False
        await store.ensure_collection(tenant_ctx, "gi_produced", edge=True)
        mock_db.create_collection.assert_called_once_with(
            "gi_produced", edge=True,
        )

    @pytest.mark.asyncio
    async def test_noop_when_exists(self, store, tenant_ctx, mock_db):
        mock_db.collection_exists.return_value = True
        await store.ensure_collection(tenant_ctx, "gi_commits")
        mock_db.create_collection.assert_not_called()

    @pytest.mark.asyncio
    async def test_swallows_creation_failure(self, store, tenant_ctx, mock_db):
        mock_db.collection_exists.return_value = False
        mock_db.create_collection.side_effect = RuntimeError("duplicate")
        await store.ensure_collection(tenant_ctx, "gi_commits")


class TestDocumentHelpers:

    @pytest.mark.asyncio
    async def test_get_document_found(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = [{"_key": "c1", "op": "x"}]
        doc = await store.get_document(tenant_ctx, "gi_commits", "c1")
        assert doc["_key"] == "c1"
        aql = mock_db.execute_query.call_args.args[0]
        binds = mock_db.execute_query.call_args.kwargs["bind_vars"]
        assert "doc._key == @key" in aql
        assert binds == {"@collection": "gi_commits", "key": "c1"}

    @pytest.mark.asyncio
    async def test_get_document_missing(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = []
        assert await store.get_document(tenant_ctx, "gi_commits", "c1") is None

    @pytest.mark.asyncio
    async def test_upsert_document(self, store, tenant_ctx, mock_db):
        await store.upsert_document(
            tenant_ctx, "gi_commits", {"_key": "c1", "op": "x"},
        )
        aql = mock_db.execute_query.call_args.args[0]
        binds = mock_db.execute_query.call_args.kwargs["bind_vars"]
        assert "UPSERT" in aql and "REPLACE @doc" in aql
        assert binds["key"] == "c1"
        assert binds["doc"]["op"] == "x"

    @pytest.mark.asyncio
    async def test_insert_document(self, store, tenant_ctx, mock_db):
        await store.insert_document(
            tenant_ctx, "gi_commit_items", {"item_key": "a"},
        )
        aql = mock_db.execute_query.call_args.args[0]
        assert "INSERT @doc IN @@collection" in aql

    @pytest.mark.asyncio
    async def test_remove_document(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = ["c1"]
        assert await store.remove_document(tenant_ctx, "gi_concepts", "c1")
        aql = mock_db.execute_query.call_args.args[0]
        assert "REMOVE doc IN @@collection" in aql

    @pytest.mark.asyncio
    async def test_remove_document_missing(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = []
        assert not await store.remove_document(tenant_ctx, "gi_concepts", "c1")


class TestQueryDocuments:

    @pytest.mark.asyncio
    async def test_filters_sort_and_limit(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = [{"seq": 2}]
        rows = await store.query_documents(
            tenant_ctx,
            "gi_commits",
            filters={"run_id": "r1"},
            sort_desc="seq",
            limit=5,
        )
        assert rows == [{"seq": 2}]
        aql = mock_db.execute_query.call_args.args[0]
        binds = mock_db.execute_query.call_args.kwargs["bind_vars"]
        assert "FILTER doc.run_id == @f0" in aql
        assert "SORT doc.seq DESC" in aql
        assert "LIMIT 5" in aql
        assert binds["f0"] == "r1"

    @pytest.mark.asyncio
    async def test_rejects_invalid_field(self, store, tenant_ctx, mock_db):
        with pytest.raises(ValueError):
            await store.query_documents(
                tenant_ctx, "gi_commits", filters={"x == 1 REMOVE doc": "y"},
            )

    @pytest.mark.asyncio
    async def test_rejects_invalid_sort_field(self, store, tenant_ctx, mock_db):
        with pytest.raises(ValueError):
            await store.query_documents(
                tenant_ctx, "gi_commits", sort_desc="seq DESC REMOVE doc",
            )


class TestEdgeHelpers:

    @pytest.mark.asyncio
    async def test_get_all_edges(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = [{"source_id": "a"}]
        edges = await store.get_all_edges(tenant_ctx, "gi_references")
        assert edges == [{"source_id": "a"}]

    @pytest.mark.asyncio
    async def test_get_all_edges_failure_returns_empty(
        self, store, tenant_ctx, mock_db,
    ):
        mock_db.execute_query.side_effect = RuntimeError("boom")
        assert await store.get_all_edges(tenant_ctx, "gi_references") == []

    @pytest.mark.asyncio
    async def test_edges_incident(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = []
        await store.edges_incident(tenant_ctx, "gi_references", "n1")
        aql = mock_db.execute_query.call_args.args[0]
        binds = mock_db.execute_query.call_args.kwargs["bind_vars"]
        assert "e.source_id == @node_id OR e.target_id == @node_id" in aql
        assert binds["node_id"] == "n1"

    @pytest.mark.asyncio
    async def test_remove_edge_by_triple(self, store, tenant_ctx, mock_db):
        mock_db.execute_query.return_value = ["k1"]
        removed = await store.remove_edge_by_triple(
            tenant_ctx, "gi_references", "a", "b", "references",
        )
        assert removed
        binds = mock_db.execute_query.call_args.kwargs["bind_vars"]
        assert binds["src"] == "a"
        assert binds["tgt"] == "b"
        assert binds["kind"] == "references"
