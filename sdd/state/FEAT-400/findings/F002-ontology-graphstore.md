---
id: F002
slug: ontology-graphstore
query: "OntologyGraphStore ArangoDB wrapper and persistence patterns"
type: read
---

# F002: OntologyGraphStore & GraphIndex Persistence

## OntologyGraphStore (ontology/graph_store.py:33)

- Wraps `asyncdb.AsyncDB` ArangoDB client (does NOT own connection)
- Tenant isolation: each tenant gets own ArangoDB database (`db_{tenant_id}`)
- `_get_db()`: calls `await self._client.use(ctx.arango_db)` before every op
- Key methods: `initialize_tenant()`, `upsert_nodes()`, `create_edges()`, `get_all_nodes()`, `soft_delete_nodes()`, `execute_traversal()`
- AQL UPSERT pattern: `UPSERT {key} INSERT doc UPDATE doc IN @@collection` with batch+fallback
- Named graph: `{tenant_id}_ontology_graph`

## Connection Pattern (loader.py:296-313)

```python
from asyncdb import AsyncDB
db = AsyncDB("arangodb", params={host, port, protocol, username, password, database})
await db.connection()
store = OntologyGraphStore(arango_client=db)
```

## Credential Resolution (loader.py:315-369)

- `ARANGODB_HOST` (default "127.0.0.1")
- `ARANGODB_PORT` (default 8529)
- `ARANGODB_PROTOCOL` (default "http")
- `ARANGODB_USERNAME` (default "root")
- `ARANGODB_PASSWORD` (default "")
- `ARANGODB_DATABASE` (default `db_{tenant_id}`)

## GraphIndexPersistence (persist.py:101)

- Routes nodes to per-kind gi_* vertex collections
- Routes edges to per-kind gi_* edge collections
- `persist_graph()`: bulk upsert grouped by kind
- `replace_document_slice()`: atomic soft-delete + re-upsert per document_uri
- LACKS audit/commit/revert protocol (SQLitePersistence has it)

## Collection Naming (meta_ontology.py)

- 9 vertex collections: gi_documents, gi_sections, gi_symbols, gi_concepts, etc.
- 10 edge collections: gi_contains, gi_references, gi_defines, etc.
- `gi_wiki_pages` already exists in the meta-ontology

## No ArangoSearch views/analyzers defined anywhere in the codebase
