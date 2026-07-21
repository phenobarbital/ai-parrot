---
type: Wiki Entity
title: OntologyGraphStore
id: class:parrot.knowledge.ontology.graph_store.OntologyGraphStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: ArangoDB wrapper for ontology graph operations.
---

# OntologyGraphStore

Defined in [`parrot.knowledge.ontology.graph_store`](../summaries/mod:parrot.knowledge.ontology.graph_store.md).

```python
class OntologyGraphStore
```

ArangoDB wrapper for ontology graph operations.

Responsibilities:
    - Create/manage vertex and edge collections per tenant.
    - Execute AQL traversals with bind variables.
    - CRUD operations for nodes and edges during ingestion.
    - Tenant-isolated: each tenant gets its own ArangoDB database.

The store does NOT own the ArangoDB connection — it receives a client
(``asyncdb.AsyncDB``) from the connection pool.

Args:
    arango_client: An ``asyncdb.AsyncDB`` instance configured for ArangoDB.

## Methods

- `async def initialize_tenant(self, ctx: TenantContext) -> None` — Create the ArangoDB database and all collections for a tenant.
- `async def execute_traversal(self, ctx: TenantContext, aql: str, bind_vars: dict[str, Any] | None=None, collection_binds: dict[str, str] | None=None) -> list[dict[str, Any]]` — Execute an AQL traversal query against the tenant's graph.
- `async def upsert_nodes(self, ctx: TenantContext, collection: str, nodes: list[dict[str, Any]], key_field: str) -> UpsertResult` — Upsert nodes into a vertex collection.
- `async def create_edges(self, ctx: TenantContext, edge_collection: str, edges: list[dict[str, Any]]) -> int` — Create edges in an edge collection.
- `async def get_all_nodes(self, ctx: TenantContext, collection: str) -> list[dict[str, Any]]` — Retrieve all active nodes from a vertex collection.
- `async def soft_delete_nodes(self, ctx: TenantContext, collection: str, keys: list[str]) -> None` — Mark nodes as inactive (soft delete).
