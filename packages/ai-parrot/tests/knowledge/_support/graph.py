"""In-memory OntologyGraphStore double shared by knowledge test suites (FEAT-601).

Promoted copy of ``tests/knowledge/contracts/test_graph_loader.py:32-146``.
"""

from __future__ import annotations

from typing import Any, Callable, Optional


class FakeUpsertResult:
    """Mimics ``OntologyGraphStore.upsert_nodes``'s return value."""

    def __init__(self, inserted: int = 0, updated: int = 0) -> None:
        self.inserted = inserted
        self.updated = updated
        self.unchanged = 0


class FakeGraphStore:
    """In-memory graph store with production-relevant edge and deletion semantics."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, dict[str, Any]]] = {}
        self.edges: dict[str, list[dict[str, Any]]] = {}
        self.fail_on: set[str] = set()
        self.swallow_writes: set[str] = set()
        self.traversals: list[tuple[str, dict[str, Any], dict[str, str]]] = []
        self._traversal_rows: list[tuple[str, Callable[[dict[str, Any]], list[dict[str, Any]]]]] = []

    async def upsert_nodes(
        self, ctx: Any, collection: str, nodes: list[dict[str, Any]], key_field: str
    ) -> FakeUpsertResult:
        """Upsert nodes by ``key_field`` and reactivate updated documents."""
        if collection in self.fail_on:
            raise RuntimeError(f"{collection} unavailable")
        bucket = self.nodes.setdefault(collection, {})
        inserted = updated = 0
        if collection in self.swallow_writes:
            return FakeUpsertResult(0, 0)
        for node in nodes:
            key = node[key_field]
            if key in bucket:
                updated += 1
            else:
                inserted += 1
            bucket[key] = {**node, "_key": key, "_active": True}
        return FakeUpsertResult(inserted, updated)

    async def get_all_nodes(self, ctx: Any, collection: str) -> list[dict[str, Any]]:
        """Return active vertices in a collection."""
        if collection in self.fail_on:
            raise RuntimeError(f"{collection} unavailable")
        return [node for node in self.nodes.get(collection, {}).values() if node.get("_active") is not False]

    async def soft_delete_nodes(self, ctx: Any, collection: str, keys: list[str]) -> None:
        """Mark matching vertices inactive."""
        bucket = self.nodes.setdefault(collection, {})
        for key in keys:
            if key in bucket:
                bucket[key]["_active"] = False

    async def create_edges(self, ctx: Any, edge_collection: str, edges: list[dict[str, Any]]) -> int:
        """Insert edges by endpoints without updating pre-existing properties."""
        bucket = self.edges.setdefault(edge_collection, [])
        created = 0
        for edge in edges:
            if any(item["_from"] == edge["_from"] and item["_to"] == edge["_to"] for item in bucket):
                continue
            bucket.append(dict(edge))
            created += 1
        return created

    async def get_all_edges(self, ctx: Any, collection: str) -> list[dict[str, Any]]:
        """Return every edge in a collection."""
        if collection in self.fail_on:
            raise RuntimeError(f"{collection} unavailable")
        return list(self.edges.get(collection, []))

    async def edges_incident(self, ctx: Any, collection: str, node_id: str) -> list[dict[str, Any]]:
        """Return edges whose source or target id is ``node_id``."""
        return [
            edge for edge in self.edges.get(collection, []) if node_id in (edge.get("source_id"), edge.get("target_id"))
        ]

    async def remove_edge_by_triple(self, ctx: Any, collection: str, source_id: str, target_id: str, kind: str) -> bool:
        """Remove an edge matching endpoints, preserving production double behaviour."""
        bucket = self.edges.get(collection, [])
        before = len(bucket)
        self.edges[collection] = [
            edge
            for edge in bucket
            if not (
                (edge.get("source_id") or edge.get("_from")) == source_id
                and (edge.get("target_id") or edge.get("_to")) == target_id
            )
        ]
        return len(self.edges[collection]) < before

    def edge_pairs(self, collection: str) -> set[tuple[str, str]]:
        """Return endpoint pairs for assertions."""
        return {
            (edge.get("source_id") or edge["_from"], edge.get("target_id") or edge["_to"])
            for edge in self.edges.get(collection, [])
        }

    def active_keys(self, collection: str) -> set[str]:
        """Return active vertex keys for assertions."""
        return {key for key, node in self.nodes.get(collection, {}).items() if node.get("_active") is not False}

    async def query_documents(
        self,
        ctx: Any,
        collection: str,
        filters: Optional[dict[str, Any]] = None,
        sort_desc: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Apply ANDed equality filters over active vertices and edges."""
        documents = [
            *self.nodes.get(collection, {}).values(),
            *self.edges.get(collection, []),
        ]
        rows = [
            document
            for document in documents
            if document.get("_active") is not False
            and all(document.get(field) == value for field, value in (filters or {}).items())
        ]
        if sort_desc is not None:
            rows.sort(key=lambda document: document.get(sort_desc), reverse=True)
        return rows[:limit] if limit is not None else rows

    async def get_document(self, ctx: Any, collection: str, key: str) -> Optional[dict[str, Any]]:
        """Return one vertex by key or ``None``."""
        return self.nodes.get(collection, {}).get(key)

    async def upsert_document(self, ctx: Any, collection: str, doc: dict[str, Any]) -> None:
        """Insert or replace a vertex by ``_key``."""
        self.nodes.setdefault(collection, {})[doc["_key"]] = {**doc, "_active": doc.get("_active", True)}

    def script_traversal(self, contains: str, rows: Callable[[dict[str, Any]], list[dict[str, Any]]]) -> None:
        """Register rows returned when an AQL query contains ``contains``."""
        self._traversal_rows.append((contains, rows))

    async def execute_traversal(
        self,
        ctx: Any,
        aql: str,
        bind_vars: Optional[dict[str, Any]] = None,
        collection_binds: Optional[dict[str, str]] = None,
    ) -> list[dict[str, Any]]:
        """Record a traversal and return the first matching scripted result."""
        bindings = bind_vars or {}
        collections = collection_binds or {}
        self.traversals.append((aql, bindings, collections))
        for contains, rows in self._traversal_rows:
            if contains in aql:
                return rows(bindings)
        return []


class FakeTenantManager:
    """Resolve a context whose ontology carries the requested entities."""

    def __init__(self, entities: tuple[str, ...] = ("Procedure", "Step", "Media", "Tip")) -> None:
        self.entities = entities
        self.calls: list[tuple[str, Optional[str]]] = []

    def resolve(self, tenant_id: str, domain: Optional[str] = None) -> Any:
        """Build a minimal tenant context for graph-loader tests."""
        self.calls.append((tenant_id, domain))
        ontology = type("Ontology", (), {"entities": {name: object() for name in self.entities}})()
        return type(
            "Ctx",
            (),
            {
                "tenant_id": tenant_id,
                "arango_db": f"{tenant_id}_ontology",
                "pgvector_schema": tenant_id,
                "ontology": ontology,
            },
        )()
