---
id: F010
query_id: Q010
type: grep
intent: "What is the GraphIndex persistence seam (arango / postgres / sqlite backends, publisher) and where does the L1 synthesis cache live?"
executed_at: 2026-11-06T13:43:00Z
duration_ms: 0
parent_id: null
depth: 1
merged_from: [FC-010, FW-003]
---

# F010 — GraphIndex has a capability-typed backend registry with sqlite / null / postgres / arangodb; Postgres is the richest; no "L1 synthesis cache" exists in code

## Summary

`graphindex/backends.py` is "the only composition root" (FEAT-540 M7): `GraphBackendSpec(name, factory="module:callable", required_options, capabilities, extra, project_options)` + `register_graph_backend` + `async create_graph_persistence(backend, **options)`. Registered: **`sqlite`** (capabilities `incremental`, `source_coherence`), **`null`**, **`postgres`** (`temporal`, `embeddings`, `hybrid`, `incremental`, `source_coherence`; extra `graphindex-postgres`) and **`arangodb`** (extra `arangodb`; no declared capabilities visible in the grep). The contract is the `GraphPersistence` Protocol plus five optional capability Protocols, with a reusable conformance suite. The Postgres plane (`pg_schema.py` + `persist_postgres.py`) is a bitemporal schema (`nodes`, `node_versions` with `EXCLUDE USING gist`, `edges`, `embeddings vector(dim)`, `symbols`, `files`, `commits`, `commit_items`, tsvector FTS) configured by `GRAPHINDEX_PG_DSN / _PG_SCHEMA / _EMBEDDING_DIM / _ANN_INDEX_KIND`. `ArangoPersistence` is the only GraphIndex consumer of the ontology `GraphDocumentStore`. **No synthesis cache**: `grep -rnE "synth|\bL1\b|\bL0\b|summary_cache"` over `knowledge/graphindex` matches only the words "synthetic" — the draft's `synth` table / "caché L1" / "L0/L1/L2" vocabulary has no counterpart in the code.

GraphIndex persistence backends satisfy one explicit `GraphPersistence` Protocol (`graphindex/protocols.py`) with optional capability Protocols, and are composed through `graphindex/backends.py` (`GraphBackendSpec`, `register_graph_backend`), with `sqlite`, `null`, `postgres` and `arangodb` registered lazily. A reusable conformance suite (`tests/knowledge/graphindex/persistence_conformance.py`) runs against sqlite/null/fake and, behind skip gates, Postgres/Arango. The server-side "central plane" the draft wants for GraphIndex already exists on PostgreSQL (`PostgresPersistence` over the `graphindex.*` schema — FEAT-520, 10/10 tasks done, `completed_at` 2026-09-03). The draft's claim that it replaces "SQLite per-repo (local)" and "ArangoDB (remoto)" backends must be read against this: Postgres is already a peer backend for both GraphIndex and the wiki.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py`
  lines: 22-52
  symbol: `GraphBackendSpec`
  excerpt: |
    class GraphBackendSpec(BaseModel):
        """Registry entry: lazy factory path, required options, declared capabilities.
        name: str
        factory: str
        required_options: tuple[str, ...] = ()
        capabilities: tuple[str, ...] = ()
        extra: str | None = None
        project_options: str | None = None
    _REGISTRY: dict[str, GraphBackendSpec] = {}

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py`
  lines: 94-116
  symbol: `create_graph_persistence`
  excerpt: |
    async def create_graph_persistence(backend: str, **options: Any) -> GraphPersistence:
        spec = graph_backend_spec(backend)
        missing = [o for o in spec.required_options if options.get(o) is None]
        if missing:
            raise ValueError(f"graph backend {backend!r} requires option(s): {', '.join(missing)}")
        factory = _import_factory(spec)
        result = factory(**options)

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py`
  lines: 235-254
  symbol: built-in backend registrations
  excerpt: |
    236:        name="sqlite",
    239:        capabilities=("incremental", "source_coherence"),
    241:    GraphBackendSpec(name="null", factory=f"{_BASE}.backends:_create_null"),
    243:        name="postgres",
    245:        capabilities=("temporal", "embeddings", "hybrid", "incremental", "source_coherence"),
    246:        extra="graphindex-postgres",
    249:        name="arangodb",
    251:        extra="arangodb",
    254:    register_graph_backend(_spec)

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py`
  lines: 102-191
  symbol: `GraphPersistence`
  excerpt: |
    class GraphPersistence(Protocol):
        """Base contract every GraphIndex backend satisfies (persist_sqlite.py is the reference).
        - ``apply_update`` is atomic ... allocates ``CommitReceipt.seq`` ... strictly monotonic per tenant
          (SQLite: rowid/seq table, Postgres: sequence, Arango: ``_next_seq`` doc; HelixDB: Meta counter);
        async def persist_graph(...); replace_document_slice(...); load_graph(...); apply_update(...)
        async def get_commit(...); list_commits(...); revert_commit(...); close()
    class IncrementalPersistence / TemporalGraphPersistence / EmbeddingPersistence /
          HybridRetrievalPersistence / SourceCoherencePersistence (Protocol)

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py`
  lines: 60-126
  symbol: `resolve_pg_settings` / `GRAPHINDEX_PG_*`
  excerpt: |
    60:DEFAULT_PG_SCHEMA = "graphindex"
    97:    schema_name = str(resolve_setting("GRAPHINDEX_PG_SCHEMA", explicit=schema, default=DEFAULT_PG_SCHEMA))
    100:        dsn=resolve_setting("GRAPHINDEX_PG_DSN", explicit=dsn),
    102:        embedding_dim=int(resolve_setting("GRAPHINDEX_EMBEDDING_DIM", default=DEFAULT_EMBEDDING_DIM)),
    103:        ann_index_kind=str(resolve_setting("GRAPHINDEX_ANN_INDEX_KIND", default=DEFAULT_ANN_INDEX_KIND)),

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py`
  lines: 211-345
  symbol: Postgres DDL
  excerpt: |
    211:CREATE TABLE IF NOT EXISTS {schema}.meta (
    216:CREATE TABLE IF NOT EXISTS {schema}.nodes (
    225:CREATE TABLE IF NOT EXISTS {schema}.node_versions (
    237:    fts          tsvector,
    245:    EXCLUDE USING gist (concept_id WITH =, validity WITH &&)
    251:CREATE TABLE IF NOT EXISTS {schema}.edges (
    281:CREATE TABLE IF NOT EXISTS {schema}.embeddings (
    285:    embedding    vector({resolve_pg_settings().embedding_dim}) NOT NULL,
    289:CREATE TABLE IF NOT EXISTS {schema}.symbols (
    314/321/334: {schema}.files, {schema}.commits, {schema}.commit_items

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py`
  lines: 207-207
  symbol: `PostgresPersistence`
  excerpt: |
    207:class PostgresPersistence:

- path: `packages/ai-parrot/tests/knowledge/graphindex/persistence_conformance.py`
  lines: 1-45
  symbol: conformance cases
  excerpt: |
    """Reusable GraphPersistence conformance cases (FEAT-540 M7).
    Import the ``case_*`` coroutines (or ``ALL_CASES`` / ``STATELESS_CASES``) from a per-backend test and call each
    with a fresh ``persistence`` and a ``ctx`` that has a ``tenant_id``.
    async def case_apply_and_revert(persistence: Any, ctx: Any) -> None:

- path: `packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py`
  lines: 119-119
  symbol: `NullPersistence`
  excerpt: |
    class NullPersistence:

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

- GraphIndex files: `backends.py`, `protocols.py`, `persist_arango.py`, `persist_postgres.py`, `persist_sqlite.py`, `pg_schema.py`, `publish.py` (`GraphPublisher` L40), `sqlite_reader.py`, plus pipeline modules. `graphindex/__init__.py:10` still documents stage 5 as "Persist — ArangoOntologyGraphStore → ArangoDB + embeddings → pgvector".
- The `GraphPersistence` docstring already names a fourth backend family ("HelixDB: Meta counter") — the registry was designed for more engines.
- The draft declares GraphIndex L0 out of scope and "L1 synth cache" in scope for SurrealDB; neither term nor a `(repo, qualified_name, content_hash) → summary` store was found. `content_hash` does exist on `graphindex.symbols` / wiki `SymbolRecord` (F009), which is structural, not an LLM-summary cache.
- [cross-lane: type=wiki_query, intent=is "GraphIndex L0/L1/L2" (structural graph / synthesis cache / QueryClassifier router) defined in any spec or proposal, or is it vocabulary from an unmerged design]
- `GraphBackendSpec` / `register_graph_backend` / `NullPersistence` / `GraphPersistence` line numbers come from one confirming grep. `create_graph_persistence` is named by TASK-4319 but did not match a `^def ` grep in `backends.py` — it may be `async def` or live elsewhere.
- Index status read directly from `sdd/tasks/index/*.json` on local `dev` (counts toward this lane's `files_read`). Local `dev` can lag feature branches; the git lane (Q105) should confirm against `origin/feat-*`.
- [cross-lane: type=grep, intent=locate create_graph_persistence (graphindex/backends.py) and the arangodb lazy factory target persist_arango.ArangoPersistence]
- [cross-lane: type=git_log, intent=confirm FEAT-520 and FEAT-540 are merged on origin/dev, not just marked done in the local index]
- Citation `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_arango.py` :: ArangoPersistence omitted here — canonical in F003.
