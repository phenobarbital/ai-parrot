---
id: FW-003
query_id: Q203
type: wiki_query
intent: "Orientation: GraphIndex postgres backend and server plane"
executed_at: 2026-11-06T13:29:04Z
duration_ms: 3500
parent_id: null
depth: 1
---

# FW-003 — GraphIndex persistence is selected through one registry (`graphindex/backends.py`, FEAT-540 M7) with built-ins sqlite, null, postgres, arangodb; the Postgres plane (FEAT-520) is done

## Summary

GraphIndex persistence backends satisfy one explicit `GraphPersistence` Protocol (`graphindex/protocols.py`) with optional capability Protocols, and are composed through `graphindex/backends.py` (`GraphBackendSpec`, `register_graph_backend`), with `sqlite`, `null`, `postgres` and `arangodb` registered lazily. A reusable conformance suite (`tests/knowledge/graphindex/persistence_conformance.py`) runs against sqlite/null/fake and, behind skip gates, Postgres/Arango. The server-side "central plane" the draft wants for GraphIndex already exists on PostgreSQL (`PostgresPersistence` over the `graphindex.*` schema — FEAT-520, 10/10 tasks done, `completed_at` 2026-09-03). The draft's claim that it replaces "SQLite per-repo (local)" and "ArangoDB (remoto)" backends must be read against this: Postgres is already a peer backend for both GraphIndex and the wiki.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py`
  lines: 22-46
  symbol: `GraphBackendSpec`
  excerpt: |
    class GraphBackendSpec(BaseModel):
    def register_graph_backend(spec: GraphBackendSpec) -> None:

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py`
  lines: 119-119
  symbol: `NullPersistence`
  excerpt: |
    class NullPersistence:

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py`
  lines: 103-103
  symbol: `GraphPersistence`
  excerpt: |
    class GraphPersistence(Protocol):

- path: `sdd/tasks/completed/TASK-4319-graph-backend-registry.md`
  symbol: `TASK-4319` (FEAT-540, status done)
  wiki_page_id: file:sdd/tasks/completed/TASK-4319-graph-backend-registry.md
  score: 1.00 (query "graphindex persistence factory backend arangodb sqlite postgres")
  excerpt: |
    One composition root: `GraphBackendSpec`, `register_graph_backend`, `create_graph_persistence`;
    built-ins sqlite, null, postgres, arangodb. SQLite and Postgres gain `close()`/`file_hashes()`.
    Create `tests/knowledge/graphindex/persistence_conformance.py` (reusable case functions) +
    `test_graph_backends.py` running them for sqlite/null/fake, Postgres/Arango behind existing skipif gates.
    # persist_postgres.py: class PostgresPersistence :207; __init__(dsn=None, *, pool=None, schema='graphindex') :226

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py`
  symbol: `_node_content_hash`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py#_node_content_hash
  score: 1.00 (Q209)
  excerpt: |
    Compute the stable no-op-detection hash for a node's persisted fields.

- path: `sdd/tasks/index/graphindex-postgres-backend.json`
  symbol: `FEAT-520`
  wiki_page_id: file:sdd/tasks/index/graphindex-postgres-backend.json
  score: 0.80
  excerpt: |
    feature_id FEAT-520 · completed_at 2026-09-03T13:29:23+00:00 · tasks: {done: 10}

## Notes

- `GraphBackendSpec` / `register_graph_backend` / `NullPersistence` / `GraphPersistence` line numbers come from one confirming grep. `create_graph_persistence` is named by TASK-4319 but did not match a `^def ` grep in `backends.py` — it may be `async def` or live elsewhere.
- Index status read directly from `sdd/tasks/index/*.json` on local `dev` (counts toward this lane's `files_read`). Local `dev` can lag feature branches; the git lane (Q105) should confirm against `origin/feat-*`.
- [cross-lane: type=grep, intent=locate create_graph_persistence (graphindex/backends.py) and the arangodb lazy factory target persist_arango.ArangoPersistence]
- [cross-lane: type=git_log, intent=confirm FEAT-520 and FEAT-540 are merged on origin/dev, not just marked done in the local index]
