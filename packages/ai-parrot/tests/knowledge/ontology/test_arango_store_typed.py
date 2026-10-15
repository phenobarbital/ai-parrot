"""Typed traversals issue the captured AQL (FEAT-540 M8)."""

from types import SimpleNamespace
from typing import Any

import pytest

from parrot.knowledge.ontology.contracts import DynamicQuery, GraphDocumentStore, OntologyTraversalStore
from parrot.knowledge.ontology.exceptions import QueryDialectMismatch, TraversalPatternUnavailable
from parrot.knowledge.ontology.graph_store import ArangoOntologyGraphStore, OntologyGraphStore


class _Client:
    """Capturing fake asyncdb client."""

    def __init__(self, rows: Any = None) -> None:
        self.rows = rows if rows is not None else []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def use(self, name: str) -> None:
        self.db = name

    async def execute_query(self, aql: str, bind_vars: dict[str, Any] | None = None) -> Any:
        self.calls.append((aql, bind_vars or {}))
        return self.rows


CTX = SimpleNamespace(arango_db="t_ontology")


def _store(rows: Any = None) -> tuple[ArangoOntologyGraphStore, _Client]:
    client = _Client(rows)
    return ArangoOntologyGraphStore(client), client


def test_contracts_and_aliases() -> None:
    store, _ = _store()
    assert isinstance(store, GraphDocumentStore)
    assert isinstance(store, OntologyTraversalStore)
    assert store.dialect == "aql"
    assert OntologyGraphStore is ArangoOntologyGraphStore
    assert ArangoOntologyGraphStore.execute_traversal is ArangoOntologyGraphStore._execute_aql


@pytest.mark.asyncio
async def test_is_reachable_aql_verbatim() -> None:
    store, client = _store(["employees/2"])
    assert await store.is_reachable(CTX, "employees/1", "employees/2", edge_collection="reports_to", max_depth=10)
    assert client.calls == [
        (
            "FOR v IN 1..10 OUTBOUND @asker_id @@edge_collection FILTER v._id == @target_id RETURN v._id",
            {"asker_id": "employees/1", "target_id": "employees/2", "@edge_collection": "reports_to"},
        )
    ]


@pytest.mark.asyncio
async def test_is_reachable_false_and_bad_direction() -> None:
    store, _ = _store([])
    assert not await store.is_reachable(CTX, "a/1", "a/2", edge_collection="e", max_depth=3)
    with pytest.raises(ValueError):
        await store.is_reachable(CTX, "a/1", "a/2", edge_collection="e", max_depth=3, direction="x; DROP")


@pytest.mark.asyncio
async def test_get_document_by_id() -> None:
    store, client = _store([{"_id": "e/1", "department": "x"}])
    assert await store.get_document_by_id(CTX, "e/1") == {"_id": "e/1", "department": "x"}
    assert client.calls == [("RETURN DOCUMENT(@target_id)", {"target_id": "e/1"})]
    store, _ = _store([None])
    assert await store.get_document_by_id(CTX, "e/9") is None


@pytest.mark.asyncio
async def test_find_by_field_aql_verbatim() -> None:
    store, client = _store([{"name": "a"}])
    await store.find_by_field(CTX, "employees", "name", "Ann")
    assert client.calls == [
        (
            "FOR e IN @@collection FILTER e.name == @mention  LIMIT 2 RETURN e",
            {"mention": "Ann", "@collection": "employees"},
        )
    ]


@pytest.mark.asyncio
async def test_find_by_field_with_filters() -> None:
    store, client = _store()
    await store.find_by_field(CTX, "employees", "name", "Ann", filters={"department": "ops"}, limit=5)
    aql, binds = client.calls[0]
    assert aql == ("FOR e IN @@collection FILTER e.name == @mention FILTER e.department == @filter_0 LIMIT 5 RETURN e")
    assert binds["filter_0"] == "ops"
    with pytest.raises(ValueError):
        await store.find_by_field(CTX, "employees", "name; x", "Ann")


@pytest.mark.asyncio
async def test_search_by_name_aql_verbatim() -> None:
    store, client = _store()
    await store.search_by_name(CTX, "employees", "AnN")
    assert client.calls == [
        (
            "FOR e IN @@collection FILTER LIKE(LOWER(e.name), CONCAT('%', @mention, '%'))  "
            "SORT LENGTH(e.name) ASC LIMIT 10 RETURN e",
            {"mention": "ann", "@collection": "employees"},
        )
    ]


@pytest.mark.asyncio
async def test_execute_query_dialect() -> None:
    store, client = _store([{"x": 1}])
    query = DynamicQuery(dialect="aql", text="FOR d IN c RETURN d", bind_vars={"a": 1}, collection_binds={"@c": "c"})
    assert await store.execute_query(CTX, query) == [{"x": 1}]
    assert client.calls == [("FOR d IN c RETURN d", {"a": 1, "@c": "c"})]
    with pytest.raises(QueryDialectMismatch):
        await store.execute_query(CTX, DynamicQuery(dialect="cypher", text="MATCH (n) RETURN n"))


@pytest.mark.asyncio
async def test_execute_pattern_template_selection() -> None:
    store, client = _store()
    implicit = SimpleNamespace(query_template="IMPLICIT")
    await store.execute_pattern(CTX, implicit, {"p": 1}, {"@c": "col"})
    assert client.calls[-1] == ("IMPLICIT", {"p": 1, "@c": "col"})
    explicit = SimpleNamespace(query_template="IMPLICIT", query_templates={"aql": "EXPLICIT", "cypher": "X"})
    await store.execute_pattern(CTX, explicit, {})
    assert client.calls[-1][0] == "EXPLICIT"
    with pytest.raises(TraversalPatternUnavailable):
        await store.execute_pattern(CTX, SimpleNamespace(query_template=""), {})
