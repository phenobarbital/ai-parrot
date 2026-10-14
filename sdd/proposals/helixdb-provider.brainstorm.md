---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: [ai-parrot, ai-parrot-tools, ci]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [helixdb, graph-database, wiki, graphindex, vector-search, bm25]
---

# Brainstorm: HelixDB graph provider

**Date**: 2026-10-14
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: A

---

## Problem Statement

AI-Parrot keeps **five local knowledge planes on SQLite** and **two shared planes on
ArangoDB**, each with its own hand-rolled graph/FTS/vector emulation:

| Plane | Today | Shape |
|---|---|---|
| LLM Wiki retrieval plane | `SQLiteWikiStore` (`wiki.db`, FTS5, `embeddings` blob table) / `ArangoDBWikiStore` / `PostgresWikiStore` | pages + edges + symbols + attrs + meta behind `BaseWikiStore` |
| GraphIndex graph memory | `SQLitePersistence` (`<tenant>.db`, `nodes_fts`) / `GraphIndexPersistence` (ArangoDB) / `PostgresPersistence` | nodes + edges + files + commit protocol (`apply_update` / `revert_commit`) |
| SDD work ledger | `LedgerStore(SQLiteWikiStore)` (`ledger.db`) | wiki plane + `ledger_state` + composable `aiosqlite` transactions |
| SQL schema overlay | `SchemaStore(SQLiteWikiStore)` (`schema.db`) | wiki plane + `columns` table |
| BookStore catalog | `CatalogStore` (sync `sqlite3`, `books_fts`) | cards + relations + judgements + communities |
| PageIndex | `JSONTreeStore` + `NodeContentStore` (.md) + `NodeEmbeddingStore` (.npy) — **not SQLite** | tree + bodies + embedding matrix; hybrid search = `bm25s` + numpy + LLM walk |
| Ontology graph | `OntologyGraphStore` (ArangoDB, raw AQL) | per-tenant vertex/edge collections + ArangoSearch views |

Graph traversal on the SQLite planes is emulated with `edges` tables and in-memory
`rustworkx` rebuilds (`sqlite_reader.py`, `communities.py`), BM25 with FTS5, vectors
with brute-force numpy over blob columns. The company-wide shared variant needs a
separate ArangoDB deployment (`docker/arango/`) with a second code path (AQL) per
plane.

**HelixDB** (Apache 2.0, Rust, [github.com/HelixDB/helix-db](https://github.com/HelixDB/helix-db))
is a labeled-property-graph database with native vector (HNSW-style, cosine /
euclidean / manhattan) and BM25 text indexes in one transactional engine, usable
**embedded in-process** (`helix-db-embedded`, InMemory / Disk / S3) or as a **server**
(`ghcr.io/helixdb/helixdb:v0.0.12`, `POST /v2/query`). Since the v3 generation there
is **no compile/deploy step**: queries are JSON operation trees built by the Python
DSL at runtime, so one backend implementation can serve both the local and the shared
deployment. The goal of this feature is a `helixdb` backend for every plane above —
local (replacing SQLite) and shared (replacing ArangoDB) — selected by configuration,
with the existing backends untouched.

**Who is affected**: developers running `wikitoolkit` / the MCP server locally,
agents using GraphIndex memory and the ontology toolkit, ops running the shared wiki
(`docker/arango` today), and CI (new native wheel).

---

## Constraints & Requirements

- **Drop-in**: every consumer keeps talking to `BaseWikiStore`, the `SQLitePersistence`
  duck-typed persistence surface, `OntologyGraphStore`, `CatalogStore` and
  `HybridPageIndexSearch`. No consumer code path forks on backend.
- **Both deployment modes from one code path**: `helixdb` backend resolves to a server
  URL (shared / local-server) or an embedded source (tests / single-process tools).
- **Local multi-process writes stay safe** (Round 2a decision): the local mode is a
  long-lived HelixDB **server** (docker or `helix start --disk`) and every process is an
  HTTP client. Embedded `Disk`/`InMemory` is reserved for tests and single-process
  tools, because embedded HelixDB is a single-writer engine and the wiki plane is
  written concurrently by the git post-commit hook (`wikitoolkit upsert --changed`),
  the `wikitoolkit` MCP server and parallel agent sessions.
- **Packaging** (Round 2d decision): modules live in core `packages/ai-parrot/src/parrot/`
  behind an optional extra `ai-parrot[helixdb]`; the HTTP client (`helix-db`) depends on
  `httpx`, which is allowed **only async** (`helixdb.AsyncClient`) and only inside the
  provider module via a `ruff.toml` per-file `TID251` exemption. Never the sync
  `helixdb.Client` in an async path.
- **Scope** (Round 1a + 2b + 2c decisions): wiki plane, GraphIndex persistence, ledger +
  schema overlay planes, Ontology graph store (AQL callers rewritten), PageIndex and
  BookStore as **projections** (files/SQLite stay canonical; HelixDB is the search +
  graph plane). Full backend implementation now, **ignoring FEAT-540**'s in-flight
  tasks on the same files (merge conflicts resolved at merge time).
- **Infra deliverables** requested: `docker/helixdb/` (Dockerfile + compose), Makefile
  targets, `pyproject.toml` extra, env/config wiring.
- **Platform**: `helix-db-embedded` 0.3.3 ships wheels for manylinux_2_28 (x86_64,
  aarch64), macOS universal2, win_amd64; Python ≥3.10 (repo is ≥3.11,<3.14). The native
  `.so` is 77 MB (27 MB wheel) — must not become a core dependency.
- **Async-first**: embedded calls are native UniFFI futures; server calls go through
  `httpx.AsyncClient` pooling. Sync consumers (`CatalogStore`, `SourceCollectionManager`
  CLI paths) reuse the existing `_run_async` bridge pattern (`wiki/sources.py:1224`).
- **No hidden behaviour change for `sqlite`/`memory`/`arangodb`/`postgres`** backends.
  ArangoDB is **not** being retired: HelixDB is an additional supported backend, so no
  deprecation warnings, doc redirects or removals touch the ArangoDB code or `docker/arango`.
- **Secrets from env only** (`HELIXDB_URL`, `HELIXDB_API_KEY`), resolved via the existing
  `_env_credential()` chain (os.environ → navconfig → default), like `ARANGODB_*`.

---

## Options Explored

### Option A: Core `helixdb` backend per plane + shared client/bootstrap module (recommended)

Add one shared module `parrot/knowledge/helix/` (client resolution + label/index
bootstrap + DSL helpers) and one backend class per plane, each registered in the
plane's existing selection seam:

| Plane | New backend | Selection seam that gains `"helixdb"` |
|---|---|---|
| Wiki | `wiki/helix_store.py: HelixWikiStore(BaseWikiStore)` | `create_wiki_store()` (`wiki/store.py:2665`), `WikiConfig.storage_backend` Literal (`wiki/models.py:114`), `WikiProjectConfig.backend` Literal (`wiki/project.py:605`), `WikiNamespaceConfig.backend` (`project.py:186`), CLI `--backend` / `WIKI_STORE_BACKEND`, `SourceCollectionManager(backend=…)` (`wiki/sources.py:148`) |
| GraphIndex | `graphindex/persist_helix.py: HelixPersistence` (mirrors `SQLitePersistence` incl. commit protocol) | `build_graph_memory_toolkit(backend=…)` (`graphindex/factory.py:205`), `GraphIndexLoader._make_persistence()` (`loader.py:288`), `wiki/runtime.py:91`, `wiki/cli.py:4011/4108/4561/4623`, `flows/dev_loop/graph_memory.py:142` |
| Ledger | `wiki/ledger/store.py: LedgerStore` gains a backend-agnostic transaction accumulator; `HelixLedgerStore` composes `HelixWikiStore` | `LedgerService.from_root/from_dir` (`ledger/service.py:140,164`) |
| Schema overlay | `HelixSchemaStore` composing `HelixWikiStore` + `Column` nodes | `SchemaPlaneService.from_root/from_dir` (`schema/service.py:66,82`) |
| Ontology | `ontology/helix_graph_store.py: HelixOntologyGraphStore` with the same method surface as `OntologyGraphStore`; `execute_traversal(aql)` replaced by typed traversal methods | `GraphIndexLoader` (`loader.py:313`), `parrot_tools/graphindex/flowtask.py:220`, `parrot_tools/legal/wiki_store.py`, `parrot_tools/legal/boe/sync.py`; AQL call sites in `ontology/authorization.py` (2), `entity_resolver.py` (3), `mixin.py` (3) move to the typed methods |
| PageIndex | `pageindex/helix_projection.py` — projects tree nodes (title/summary/body, `embedding`) + `CHILD_OF` edges; `HybridPageIndexSearch` delegates `_bm25_rank` / `_vec_rank` to HelixDB when a projection is configured | `PageIndexToolkit.__init__` (`pageindex/toolkit.py:114-133`), `hybrid_search.py:163-263` |
| BookStore | `bookstore/helix_projection.py` — `Book` nodes + `RELATES_TO` edges + communities; `CatalogStore.search()` delegates when projected | `Library._catalogs` (`bookstore/library.py:230`), `library.search()` (`:411`) |

Plus infra: `docker/helixdb/{Dockerfile,docker-compose.yml,README.md}` on
`ghcr.io/helixdb/helixdb:v0.0.12` with `HELIX_DATA_DIR` volume persistence and
`/readyz` healthcheck and an image tag read from `${HELIXDB_IMAGE_TAG:-v0.0.12}`; one
Makefile target `docker-helixdb` (compose up, disk persistence — no embedded target, see
open question #2); `ai-parrot[helixdb]` extra (`helix-db==0.3.4`) and
`ai-parrot[helixdb-embedded]` (`+ helix-db-embedded==0.3.3`); `HELIXDB_URL`,
`HELIXDB_API_KEY`, `HELIXDB_MODE` settings.

**Data-model mapping** (the part that makes it "drop-in"):

- Node labels per plane (`Page`, `Symbol`, `Source`, `Meta`, `PageAttr`, `GNode`,
  `GCommit`, `GCommitItem`, `GFile`, `Column`, `TreeNode`, `Book`, ontology entity
  labels). HelixDB node ids are u64 sequences, so every user key (`concept_id`,
  `node_id`, `source_id`, `book_id`) is a **unique equality index** property and all
  lookups go through `n_where(SourcePredicate.eq(...))`.
- Edges keep `(src, dst, rel, provenance)` as `rel`-labelled edges with properties; the
  SQLite `INSERT OR REPLACE` on `(src,dst,rel)` becomes "find edge via
  `out_e(rel).where(dst)` else `add_e`" inside one write batch (HelixDB is a multigraph
  and does not dedupe).
- `pages_fts` (multi-column FTS5) becomes a BM25 **text index on one `search_text`
  property** (title + summary + body concatenated at write time; HelixDB text indexes are
  single-property, top-level only), queried with `text_search_nodes(label, prop, q, k)`
  and projected with `$score`. Whole-index searches are capped at 800 hits; per-document
  admission is ~64 MiB analysis / ~16k unique terms, far above `body_max_chars` (16,000).
- `embeddings` blob table becomes **lazy per-dimension vector indexes**: the first vector
  of length *d* written for a label creates the property `embedding_<d>` and a cosine
  index on it; `search_vector()` picks the index matching the query vector's length and
  maps to `vector_search_nodes(...)` with `$distance` (open question #1, resolved).
- Index DDL is asynchronous: bootstrap issues `create_index_if_not_exists` /
  `create_text_index_nodes` / `create_vector_index_nodes` and polls
  `get_index_operation` until active (replaces `_migrate()` on open).
- Write batches are atomic (`write_batch` commits or rolls back as a whole), which maps
  `replace_source_slice` (drop slice + add) and the GraphIndex commit protocol
  (`apply_update`, `revert_commit`) to single batches. `compare_and_swap_page` uses
  conditional entries (`var_as_if(BatchCondition.var_empty/var_not_empty)`) on a
  `content_hash` predicate and reports whether the write landed.
- Read-after-write is safe: default search consistency is `strong` (committed but
  unpublished index work is included).
- Tenancy: GraphIndex's one-file-per-tenant becomes one HelixDB `database` per tenant
  (server `gi_<tenant>`, embedded `Disk(root, tenant)`); no `tenant_id` query filters
  (open question #7, resolved).

✅ **Pros:**
- One backend implementation serves local (server or embedded) and shared deployments;
  no AQL/SQL fork per plane.
- Native graph + BM25 + vector in one transaction; removes the rustworkx rebuild and the
  numpy brute-force vector scan for the wiki and GraphIndex planes.
- Fits every existing selection seam; `sqlite`/`arangodb`/`postgres` keep working.
- `helix-db`'s `NativeGraph` (Leiden, Louvain, betweenness, shortest path) can later
  replace the `leidenalg`/`python-igraph` optional dependency in `communities.py`.
- Server mode is the documented development target and runs unchanged on Helix Cloud.

❌ **Cons:**
- Large blast radius: seven planes, ~15 call sites, config Literals in three places,
  CLI flags, docs; conflicts with FEAT-540 and FEAT-633 (TASK-4092/4093) on
  `wiki/store.py`, `graphindex/loader.py`, `ontology/graph_store.py`.
- `LedgerStore.ledger_transaction()` yields a raw `aiosqlite.Connection` (10 call
  sites) — a leaky abstraction that must be reshaped into a backend-neutral batch
  accumulator before a HelixDB ledger is possible.
- Ontology AQL rewrite touches security-sensitive code (`authorization.py`).
- `httpx` enters the dependency tree (confined to one exempted module).
- The embedded native wheel (27 MB) must be installed in CI for the unit tier, or those
  tests skip.
- HelixDB server image is v0.0.12 (young; index-storage version bumped twice in the
  last three releases — pin the tag, back up before upgrades).

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `helix-db==0.3.4` | Python SDK: `AsyncClient`, DSL (`read_batch`/`write_batch`/`g()`), `QueryRequest`, index specs | Pure Python; depends on `httpx<1,>=0.28.1`; `AsyncClient.embedded()` lazily imports `helixdb_uniffi` |
| `helix-db-embedded==0.3.3` | Native UniFFI runtime (`helixdb_uniffi.HelixDb.open/open_reader`, `query_json`) | 27 MB wheel, manylinux_2_28 x86_64/aarch64, macOS, Windows; Beta classifier |
| `ghcr.io/helixdb/helixdb:v0.0.12` | Standalone server (`POST /v2/query`, `/healthz`, `/readyz`, container port 8080) | Runs as uid 65532; `HELIX_DATA_DIR` for native disk persistence; memory mode by default |
| `httpx` (transitive) | Async transport of `helix-db` | Banned repo-wide by TID251; per-file exemption only for `parrot/knowledge/helix/client.py` |
| `aiohttp` (existing) | Healthcheck / readiness probe before opening a server client | Keeps probing code inside the convention |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:553` — `BaseWikiStore` contract and `register_wiki_backend()` (`:539`) / `_EXTRA_BACKENDS` (`:529`) seam; `create_wiki_store()` (`:2665`).
- `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py:137` — `ArangoDBWikiStore`: the most complete server-backend precedent (`initialize()`, `close()`, symbols, CAS).
- `packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py:127` — `PostgresWikiStore`: second server precedent (FEAT-520) incl. lazy-import and DSN defaults.
- `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py:138` — `SQLitePersistence`: the public surface to mirror (`persist_graph`, `replace_document_slice`, `is_stale`, `load_graph`, `apply_update`, `get_commit`, `list_commits`, `revert_commit`).
- `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:207` — `PostgresPersistence`: third mirror incl. `close()`.
- `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py:197` — `build_graph_memory_toolkit(backend=...)` lazy-import dispatch.
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py:851` — `resolve_arango_params()` + `_env_credential()` (`:822`): template for `resolve_helix_params()`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py:1224-1395` — `_run_async` bridge and the `arangodb` branch of `SourceCollectionManager`.
- `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py:163-263` — `_rebuild_bm25`, `_bm25_rank`, `_vec_rank`, `_rrf_fuse` seams.
- `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:163` — `CatalogStore` (`search`, `upsert_relations`, `upsert_communities`).
- `docker/arango/{Dockerfile,docker-compose.yml,README.md}` — compose + healthcheck + env conventions to clone for `docker/helixdb/`.
- `packages/ai-parrot/tests/knowledge/wiki/test_arango_store_cas.py:17-44` — reachability `skipif` gate pattern for live-server tests; `test_extra_backends.py` — backend-registration tests.
- `packages/ai-parrot/src/parrot/_imports.py:110` — `lazy_import(module_path, package_name, extra)` for the optional-extra error message.

---

### Option B: Satellite distribution `ai-parrot-helixdb` (PEP 420 namespace)

Same backends, shipped from `packages/ai-parrot-helixdb/src/parrot/{knowledge/wiki/helix_store.py, …}`
that merge into the `parrot.*` namespace (precedent: `ai-parrot-embeddings`), registering
the wiki backend through `register_wiki_backend("helixdb", …)` and the GraphIndex /
ontology backends through small new registries.

✅ **Pros:**
- Core stays free of `httpx` and of the native wheel; TID251 exemption lives in the
  satellite's own ruff config.
- Independent release cadence for a young upstream (v0.0.x server).
- Clean "no satellite → no backend" failure (`ValueError: Unknown wiki storage backend`).

❌ **Cons:**
- GraphIndex, Ontology, PageIndex and BookStore have **no** registration seam today —
  the satellite would still need core edits to add them, so the isolation is partial.
- A ninth distribution to version, build and publish (release skill, PyPI, CI matrix).
- Rejected by the user in Round 2d.

📊 **Effort:** High (A + packaging)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| same as A | | plus a new `pyproject.toml` + `[tool.uv.sources]` workspace entry |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-embeddings/pyproject.toml` + `src/parrot/` (no `__init__.py`) — namespace-satellite layout.
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:539` — `register_wiki_backend()`.

---

### Option C: HelixDB as a search/graph **sidecar** only (unconventional)

Keep SQLite (and files) canonical for every plane. Add one generic projector that
mirrors any `BaseWikiStore` / `SQLitePersistence` write into HelixDB (dual-write, like
the PageIndex/BookStore projection in A), and route only the expensive operations —
BM25, vector search, multi-hop neighbours, community detection via `NativeGraph` —
to HelixDB when it is reachable, falling back to SQLite otherwise.

✅ **Pros:**
- Lowest risk: no plane changes its source of truth; the ledger and schema stores stay
  pure SQLite; `WikiStoreBusy` / WAL semantics untouched.
- Immediate wins where SQLite is weakest (vector scan, graph walks, communities).
- Embedded single-writer limitation is irrelevant (the projector is the only writer).

❌ **Cons:**
- Not an ArangoDB replacement: shared deployments still need SQLite + sync or Arango.
- Dual-write drift; every lint rule (`index_drift`, `broken_edges`) needs a HelixDB twin.
- Does not meet the "drop-in replacement of SQLite" requirement.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `helix-db` + `helix-db-embedded` | projector + `Client.graph()` native algorithms | `NativeGraph` exists only on the **sync** `Client` (`AsyncClient` has no `graph()`), so algorithms run via `asyncio.to_thread` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py:33-39,541-553` — Leiden/Louvain selection to be swapped for `NativeGraph.leiden()`.
- `packages/ai-parrot/src/parrot/knowledge/graphindex/sqlite_reader.py` — HOT/COLD reader whose rustworkx rebuild the sidecar would make unnecessary.

---

### Option D: Port AQL to Cypher over HelixDB's `/v2/cypher` (unconventional, for the Ontology plane only)

HelixDB **source builds** accept Cypher reads/CRUD through `POST /v2/cypher`, `helix cypher`
and embedded clients. Translating the ~10 ontology AQL call sites to Cypher strings
would keep `execute_traversal(query: str)` string-based.

✅ **Pros:**
- Smallest diff in `authorization.py` / `entity_resolver.py` / `mixin.py`.

❌ **Cons:**
- Cypher support is documented **only for source builds**; it is unverified in the
  published `v0.0.12` image and the `helix-db-embedded` 0.3.3 wheel (open question #3).
- Keeps string queries in security-sensitive code instead of typed traversals.
- The Python SDK 0.3.4 exposes no `cypher()` method — raw HTTP would be needed.

📊 **Effort:** Low (if available) / blocked (if not)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| raw `aiohttp` POST to `/v2/cypher` | Cypher execution | no SDK support |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:271` — `execute_traversal(ctx, aql, bind_vars, collection_binds)`.

---

## Recommendation

**Option A** is recommended because it is the only option that satisfies the user's
three locked decisions at once — full backend implementation, core modules behind an
extra, and one code path for local and shared deployments — while every plane already
exposes a selection seam (`create_wiki_store`, `build_graph_memory_toolkit`,
`_make_persistence`, service `from_root/from_dir`) that a core backend plugs into
without new registries.

What is traded off: (1) `httpx` enters the tree, confined to one exempted module and
async-only; (2) the blast radius overlaps FEAT-540 and FEAT-633 — the user explicitly
chose to proceed and resolve at merge time; (3) `LedgerStore.ledger_transaction()`'s
`aiosqlite.Connection` leak must be reshaped (hard cut, no external consumers); (4) the
embedded wheel is used only for tests, so the single-writer limitation never reaches the
multi-process local workflow.

Option C is kept as the fallback shape for PageIndex and BookStore (the user chose
projection for those two). Option D is recorded for history only: the user ruled Cypher
out of scope (open question #3), so the ontology port uses typed traversals.

---

## Feature Description

### User-Facing Behavior

- `.parrot/wiki.json` accepts `"backend": "helixdb"` (also `wikitoolkit build --backend helixdb`,
  `WIKI_STORE_BACKEND=helixdb`), plus `helix_database` (default `wiki_<wiki_name>`),
  `helix_credentials_env` (default `"HELIXDB"` → `HELIXDB_URL`, `HELIXDB_API_KEY`) and
  `helix_mode` (`"server"` default; `"embedded"` opens `Disk(<storage_dir>/helix, <database>)`).
- `make docker-helixdb` starts `docker/helixdb/` (persistent `HELIX_DATA_DIR` volume,
  `127.0.0.1:6969`, readiness-gated, image `${HELIXDB_IMAGE_TAG:-v0.0.12}`). There is no
  Makefile entry for embedded mode; embedded is a test fixture.
- `pip install ai-parrot[helixdb]` (server client) / `ai-parrot[helixdb-embedded]`
  (adds the native runtime). Selecting `helixdb` without the extra fails with the
  `lazy_import` message naming the extra — never a silent fallback (same rule as
  `arangodb` / `postgres`).
- `build_graph_memory_toolkit(backend="helixdb", helix_url=…, tenant_id=…)` and
  `GraphIndexLoader(helix_params=…)` give agents HelixDB-backed graph memory with the
  same `GraphPublisher` commit/revert semantics.
- `wikitoolkit ledger …` and the schema plane work unchanged on either backend.
- PageIndex and BookStore keep their files/SQLite; when a HelixDB projection is
  configured, BM25 and vector ranking are served by HelixDB and the result lists are
  identical in shape.
- A shared company wiki switches from `docker/arango` to `docker/helixdb` by changing
  `backend` and `HELIXDB_URL`; namespaces (`WikiNamespaceConfig`) can point at a HelixDB
  database the same way they point at an ArangoDB database today.

### Internal Behavior

1. **Client resolution** (`parrot/knowledge/helix/client.py`): `resolve_helix_params(config)`
   produces either `{"url", "api_key"}` or `{"source": Disk|InMemory}`; `open_helix_client()`
   returns an `AsyncClient` (server via `AsyncClient(url, api_key=…, timeout=…)`, embedded via
   `AsyncClient.embedded(source)` / `embedded_reader(source)` for `read_only`). A server
   client is preceded by an `aiohttp` probe of `/readyz` with a bounded retry so hook
   invocations fail fast with a clear message when the container is down.
2. **Bootstrap** (`helix/bootstrap.py`): idempotent per-plane label/index declarations
   (unique equality indexes on user keys, equality indexes on `category`/`source_id`/
   `rel`, text index on `search_text`, vector index on `embedding` with the configured
   dimension). Issues `create_*_index*` in one write batch, then polls
   `get_index_operation` receipts until `IndexOperationSucceeded` / already-active.
   Records `schema_version` in a `Meta` node (same key as SQLite `meta`).
3. **Wiki store** (`HelixWikiStore`): each `BaseWikiStore` method is one `read_batch`
   or `write_batch`. Writes that replace rows (`upsert_pages`, `add_edges`,
   `replace_source_slice`, `upsert_symbols`, `upsert_attrs`) are single atomic batches:
   look up by unique key → `set_property`/`add_n`, drop-then-add for slices. Reads project
   the exact column sets consumers expect (`get_page`, `list_pages`, `neighbors`,
   `dump_*`, `stats`, lint methods `orphan_sources`/`broken_edges`/`missing_bodies`,
   `rebuild_index` → re-issue index DDL, `index_drift` → compare node counts vs index
   receipts).
4. **GraphIndex persistence** (`HelixPersistence`): `GNode`/`GEdge`/`GFile` labels plus
   `GCommit`/`GCommitItem` nodes for the commit protocol; `apply_update` writes graph
   change + commit record in one batch; `revert_commit` replays items in reverse
   seq order inside one batch (conflict detection via `seq` equality index, as in
   SQLite). `load_graph` streams `value_map` projections into `UniversalNode`/`UniversalEdge`.
5. **Ledger / schema**: `LedgerStore.ledger_transaction()` becomes a backend-neutral
   context that yields a *write accumulator* (SQLite: wraps the connection; HelixDB:
   collects a `write_batch`), committed at exit; `ledger_state` → `Meta` keys;
   `columns` → `Column` nodes with `COLUMN_OF` edges to table pages.
6. **Ontology**: `HelixOntologyGraphStore` implements `initialize_tenant`, `upsert_nodes`,
   `create_edges`, `get_all_nodes`, `soft_delete_nodes`, document CRUD, `edges_incident`,
   `remove_edge_by_triple` with typed traversals; `execute_traversal(aql)` is replaced
   by named traversal methods (`neighbours_within(depth, labels)`, `path_between`,
   `nodes_matching(filters)`) that the AQL call sites in `authorization.py`,
   `entity_resolver.py` and `mixin.py` call instead; the ArangoDB store keeps the AQL
   implementations of the same typed methods.
7. **Projections**: PageIndex writes (`JSONTreeStore.save`, `NodeContentStore.save`,
   `NodeEmbeddingStore.build_tree_matrix`) emit a projection batch; `HybridPageIndexSearch`
   calls `text_search_nodes`/`vector_search_nodes` instead of `bm25s`/numpy when a
   projection handle is injected; BookStore `CatalogStore.upsert/upsert_relations/
   upsert_communities` mirror into `Book` nodes and `search()` delegates.
8. **Tests**: unit tier on embedded `InMemory` — CI installs `helix-db-embedded`, so
   these run on every PR (local runs without the wheel skip with a clear reason); a
   parity suite runs the existing CAS/attrs/symbols tests against
   `helixdb`; a live tier gated by `HELIXDB_URL` reachability (clone of the ArangoDB
   `skipif`) exercises the docker server; the GraphIndex commit-protocol tests run
   against `HelixPersistence`.

### Edge Cases & Error Handling

- **Extra missing**: `ImportError` → `lazy_import` message naming `ai-parrot[helixdb]`
  (or `[helixdb-embedded]` for `helix_mode=embedded`).
- **Server down / not ready**: readiness probe fails → `HelixUnavailable` raised at store
  open; the post-commit hook path logs and exits non-fatally like a `WikiStoreBusy`.
- **Index backfill pending**: searches use `strong` consistency; bootstrap waits for
  activation with a bounded timeout and reports `IndexOperationBlocked` details
  (duplicate keys on a unique index, `oversized_entity`) instead of hanging.
- **Oversized text**: `active_text_mutation_limit_exceeded` (HTTP 400) aborts the whole
  batch; the store truncates `search_text` to the configured `body_max_chars` before
  writing and surfaces the error with the offending `concept_id`.
- **Result cap**: whole-index text/vector searches cap at 800; `limit` is clamped and
  documented.
- **Embedded single writer**: a second embedded writer on the same `Disk` source is an
  error; `helix_mode=embedded` is refused when a `wiki.lock` (`project.py:76`) holder
  exists, with a message pointing to server mode.
- **New vector dimension**: a vector whose length has no index yet triggers the lazy
  creation of `embedding_<d>` + its index inside the same write path (bootstrap helper,
  receipt-polled); a query vector whose length matches no index returns an empty result
  with a logged warning rather than an error.
- **Read-only planes** (federated namespaces): `embedded_reader` / server client with
  `_assert_writable()` raising `PermissionError` as today.
- **Server upgrades**: the compose file reads `${HELIXDB_IMAGE_TAG:-v0.0.12}`; the README
  documents the one-way index-storage-version upgrade and the manual `HELIX_DATA_DIR`
  volume backup to run before changing the tag.

---

## Capabilities

### New Capabilities
- `helixdb-client-bootstrap`: shared client resolution, readiness probe, label/index
  bootstrap with receipt polling, settings (`HELIXDB_*`), extras, docker and Makefile.
- `helixdb-wiki-store`: `HelixWikiStore` + `SourceCollectionManager` backend + config
  Literals + CLI/env selection + parity tests.
- `helixdb-graphindex-persistence`: `HelixPersistence` with the commit protocol wired
  into factory, loader, runtime, CLI and dev-loop graph memory.
- `helixdb-ledger-schema-planes`: backend-neutral ledger transaction accumulator +
  HelixDB ledger and schema stores.
- `helixdb-ontology-graph-store`: typed traversal surface on `OntologyGraphStore`,
  AQL call-site migration, HelixDB implementation.
- `helixdb-pageindex-bookstore-projection`: dual-write projections and search delegation.

### Modified Capabilities
- `wikitoolkit-arangodb-backend` (FEAT-400): `WikiNamespaceConfig.backend` gains a
  built-in `helixdb` value; `SourceCollectionManager` backend Literal extended.
- `graphindex-postgres-backend` (FEAT-520): `build_graph_memory_toolkit(backend=…)`
  accepts `helixdb`.
- `wikitoolkit-sqlite` (FEAT-557): `LedgerStore.ledger_transaction()` signature
  changes (hard cut).
- `wikitoolkit-lint` (FEAT-625): `rebuild_index` / `index_drift` get HelixDB semantics.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/knowledge/helix/` (new) | adds | client, bootstrap, DSL helpers; only module with the `TID251` exemption |
| `parrot/knowledge/wiki/store.py` | modifies | `create_wiki_store()` branch; docstring of `BaseWikiStore` lists the backend — overlaps TASK-4092/4093 (FEAT-633) |
| `parrot/knowledge/wiki/models.py:114`, `project.py:605,186`, `sources.py:148`, `cli.py`, `entity_cli.py` | modifies | `"helixdb"` in Literals, `helix_*` config fields, `--backend` help text |
| `parrot/knowledge/wiki/helix_store.py` (new) | adds | `HelixWikiStore` |
| `parrot/knowledge/wiki/ledger/store.py`, `ledger/service.py`, `schema/store.py`, `schema/service.py` | modifies | transaction accumulator; backend dispatch in `from_root/from_dir` |
| `parrot/knowledge/graphindex/persist_helix.py` (new), `factory.py`, `loader.py`, `wiki/runtime.py`, `wiki/cli.py`, `flows/dev_loop/graph_memory.py` | adds / modifies | backend dispatch — overlaps FEAT-540 (TASK-3266/3267) |
| `parrot/knowledge/ontology/graph_store.py`, `helix_graph_store.py` (new), `authorization.py`, `entity_resolver.py`, `mixin.py` | modifies | typed traversal surface replaces raw AQL at 8 call sites |
| `parrot_tools/graphindex/flowtask.py:220`, `parrot_tools/legal/wiki_store.py`, `parrot_tools/legal/boe/sync.py` | depends on | instantiate `OntologyGraphStore` — gain a backend switch |
| `parrot/knowledge/pageindex/toolkit.py`, `hybrid_search.py`, `helix_projection.py` (new) | modifies / adds | optional projection + delegation |
| `parrot/knowledge/bookstore/catalog.py`, `library.py`, `helix_projection.py` (new) | modifies / adds | optional projection + delegation |
| `packages/ai-parrot/pyproject.toml` | modifies | extras `helixdb`, `helixdb-embedded`; markers unchanged (`live`) |
| `ruff.toml:155-163` | modifies | per-file `TID251` ignore for `parrot/knowledge/helix/client.py` |
| `docker/helixdb/` (new), `Makefile` | adds | compose stack (`HELIXDB_IMAGE_TAG`, `HELIX_DATA_DIR` volume, `/readyz`) + `docker-helixdb` target; README with the backup-before-upgrade procedure |
| CI | modifies | installs `helix-db-embedded` (27 MB) so the HelixDB unit tier runs on every PR |
| `docker/arango/`, `ArangoDBWikiStore`, `GraphIndexPersistence` | unchanged | ArangoDB remains a fully supported peer backend; no deprecation |
| `docs/wiki/cheatsheet.md`, `docs/wiki/*.md` | modifies | backend docs |

Breaking changes: `LedgerStore.ledger_transaction()` no longer yields
`aiosqlite.Connection`; `OntologyGraphStore.execute_traversal()` is removed from the
public surface in favour of typed methods (ArangoDB implementation keeps AQL internally).
No external consumers (hard cuts accepted).

---

## Code Context

### User-Provided Code

```python
# Source: user-provided (HelixDB Python SDK, server mode)
import asyncio

import httpx

from helixdb import AsyncClient

async def execute_queries():
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with AsyncClient(timeout=10.0, limits=limits) as client:
        return await asyncio.gather(
            client.query(request),
            client.execute(request, writer_only=True, timeout=2.0),
        )

results = asyncio.run(execute_queries())
```

```python
# Source: user-provided (HelixDB Python SDK, embedded mode)
import asyncio

from helixdb import AsyncClient, Disk, InMemory

async def query_embedded():
    writer = await AsyncClient.embedded(InMemory("app"))
    async with writer:
        memory_result = await writer.query(request)

    reader = await AsyncClient.embedded_reader(Disk("./data", "seeded-app"))
    async with reader:
        disk_checkpoint = await reader.query(request)

    return memory_result, disk_checkpoint

results = asyncio.run(query_embedded())
```

```bash
# Source: user-provided
python -m pip install helix-db helix-db-embedded
```

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py
SCHEMA_VERSION = "3"                                   # line 51
class SQLitePragmaPolicy(BaseModel): ...               # line 263  (busy_timeout_s: float = 15.0)
class WikiStoreBusy(sqlite3.OperationalError): ...     # line 284
class AttrsUnsupportedError(RuntimeError): ...         # line 429
class WikiPageRecord(BaseModel): ...                   # line 433
_EXTRA_BACKENDS: dict[str, Callable[..., BaseWikiStore]] = {}   # line 529
def register_wiki_backend(name: str, factory: Callable[..., BaseWikiStore]) -> None: ...  # line 539
class BaseWikiStore(ABC):                              # line 553
    supports_attrs: bool = False
    async def get_attrs(self, concept_id: str) -> dict[str, str]
    async def list_by_attrs(self, filters, *, date_key=None, since=None, until=None, limit=200) -> list[dict]
    async def upsert_attrs(self, concept_id: str, attrs, *, replace: bool = True) -> int
    # abstract:
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int
    async def add_edges(self, edges: list[tuple]) -> int
    async def replace_source_slice(self, source_id: str, pages, edges=None) -> dict[str, Any]
    async def delete_page(self, concept_id: str) -> bool
    async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict]
    async def list_pages(self, category=None, limit=100, origin=None) -> list[dict]
    async def search_fts(self, query: str, category=None, limit=10) -> list[dict]
    async def search_vector(self, embedding: list[float], limit=10) -> list[dict]
    async def neighbors(self, concept_id: str, rel=None, direction="both") -> list[dict]
    async def dump_pages(self) -> list[dict]; async def dump_edges(self) -> list[dict]
    async def stats(self) -> dict; async def orphan_sources(self) -> list[str]
    async def broken_edges(self) -> list[dict]; async def missing_bodies(self) -> list[str]
    # concrete with defaults:
    async def rebuild_index(self) -> dict  (line ~688); async def index_drift(self) -> dict[str, int]
    async def compare_and_swap_page(self, page, expected_content_hash) -> bool   # line 680
    async def get_meta(self, key: str) -> Optional[str]; async def set_meta(self, key, value) -> None  # ~714/728
    def _assert_writable(self) -> None                                           # ~737
    async def rebuild_from_tree(...)                                             # ~745
    async def upsert_symbols(...); symbols_for(rel_path); find_symbols(...); search_symbols_fts(query, limit=20)  # ~814-909
    async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]  # ~930
class SQLiteWikiStore(BaseWikiStore):                  # line 948
    def __init__(self, db_path, wiki_name="", *, read_only=False, sqlite_policy=None, persistent_writer=False)
    # extra public: checkpoint, sqlite_settings, db_path, read_only
def create_wiki_store(storage_dir, wiki_name="", backend="sqlite", **kwargs) -> BaseWikiStore  # line 2665
```

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py:137
class ArangoDBWikiStore(BaseWikiStore):   # has initialize(), close(), analyzers, database, read_only
# From packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py:127
class PostgresWikiStore(BaseWikiStore):
# From packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:362
async def open_namespace_store(name: str, cfg: WikiNamespaceConfig, *, ...)   # dispatches _EXTRA_BACKENDS at :418
```

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/models.py:114
storage_backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite", ...)
# From packages/ai-parrot/src/parrot/knowledge/wiki/project.py
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]   # line 76 (fcntl)
class WikiNamespaceConfig(BaseModel)                                           # line 186 (path | store | database | vault; backend)
class WikiProjectConfig(BaseModel):                                            # line 561
    backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite")  # line 605
    arango_database: str | None; arango_credentials_env: str; arango_text_analyzer: str   # lines 616-627
    sqlite_busy_timeout: float; sqlite_performance_pragmas: bool               # lines 687-698
    def graph_path(self, root: Path) -> Path                                   # line 721
    def db_path(self, root: Path) -> Path                                      # line 753
def _env_credential(key: str, default: Any) -> Any                             # line 822
def resolve_arango_params(config: WikiProjectConfig) -> dict[str, Any]         # line 851
def sqlite_policy_from_config(config) -> SQLitePragmaPolicy                    # line 928
```

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
class SourceCollectionManager:   # __init__ at line 144, backend: Literal["sqlite", "json", "arangodb"] = "sqlite" (line 148)
    def _run_async(self, coro) -> Any                      # line 1224 (sync→async bridge)
    async def _resolve_arango_db(self); _arango_query(aql, bind_vars); _arango_execute(aql, bind_vars)   # 1289-1319
```

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py:24
class LedgerStore(SQLiteWikiStore):
    def __init__(self, db_path: str, wiki_name="", *, read_only=False, sqlite_policy=None, persistent_writer=False)
    @asynccontextmanager
    async def ledger_transaction(self, operation: str) -> AsyncIterator[aiosqlite.Connection]   # line 54
    async def read_cursor(self) -> tuple[int, str | None]                                        # line 75
    async def upsert_pages_in(self, conn, pages) -> None; async def add_edges_in(self, conn, edges) -> None  # 107/116
# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:140,164 — LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=...)
# From packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py:48
class SchemaStore(SQLiteWikiStore):   # columns DDL at :12; upsert_columns, columns_for, find_columns, replace_schema_slice, fold_ddl_table (120-226)
# From packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py:66,82 — SchemaStore(plane_dir / "schema.db", wiki_name="schema", read_only=...)
```

```python
# From packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py:138
class SQLitePersistence:
    def __init__(self, db_dir: Path) -> None                                   # line 153
    async def persist_graph(self, ctx, nodes, edges)                           # line 263
    async def replace_document_slice(self, ctx, document_uri, nodes, edges)    # line 341
    async def is_stale(self, ctx, source_uri, mtime, sha1)                     # line 464
    async def load_graph(self, ctx) -> tuple[list[UniversalNode], list[UniversalEdge]]   # line 574
    async def apply_update(self, ctx, update: GraphUpdate) -> CommitReceipt    # line 608
    async def get_commit(...)  # 785 ; list_commits(...) # 817 ; revert_commit(...) # 856
# tables: files, nodes, edges, nodes_fts (FTS5), graph_commits, graph_commit_items   (lines 42-80)
# From packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py:213
class GraphIndexPersistence:  def __init__(self, graph_store: OntologyGraphStore)   # ArangoDB mirror
# From packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py:207
class PostgresPersistence:    # + close() :256, as_of/history/diff/upsert_embeddings/hybrid_retrieve (1175-1484)
# From packages/ai-parrot/src/parrot/knowledge/graphindex/publish.py:37
class GraphPublisher:  def __init__(self, persistence: Any, ctx: TenantContext) -> None   # line 47 (duck-typed persistence)
# From packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py
def make_stub_tenant_context(tenant_id: str) -> TenantContext                  # line 45
class HashingGraphEmbedder                                                     # line 116
async def build_graph_memory_toolkit(db_dir=None, tenant_id=..., agent_id="agent", run_id=None, embedder=None,
                                     client=None, dimension=DEFAULT_DIMENSION, backend: str = "sqlite",
                                     dsn=None, schema="graphindex") -> GraphIndexToolkit   # line 197; dispatch 249-261
# From packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py
async def _make_persistence(self) -> Any   # line 288: sqlite_dir → SQLitePersistence; else AsyncDB("arangodb") → GraphIndexPersistence (:313)
# From packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py
class AssertionMeta(BaseModel) :100 ; class UniversalNode(BaseModel) :149 ; class UniversalEdge(BaseModel) :184
class GraphUpdate(BaseModel) :233 ; class CommitReceipt(BaseModel) :269
# From packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py:33-39,541-553 — rustworkx + optional igraph/leidenalg; algorithm="leiden"|"louvain"
```

```python
# From packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py:53
class OntologyGraphStore:
    def __init__(self, arango_client: Any = None) -> None                                  # line 69
    async def initialize_tenant(self, ctx: TenantContext) -> None                          # line 91
    async def execute_traversal(self, ctx, aql: str, bind_vars=None, collection_binds=None) -> list[dict]   # line 271
    async def upsert_nodes(...) :311 ; create_edges(...) :411 ; get_all_nodes(...) :488 ; soft_delete_nodes(...) :517
    async def ensure_collection :570 ; get_document :598 ; upsert_document :622 ; insert_document :650 ; remove_document :669
    async def query_documents :697 ; get_all_edges :738 ; edges_incident :764 ; remove_edge_by_triple :791
# AQL call sites: ontology/authorization.py (2), ontology/entity_resolver.py (3), ontology/mixin.py (3)
# From packages/ai-parrot/src/parrot/knowledge/ontology/schema.py — class MergedOntology :452 ; class TenantContext :529
```

```python
# From packages/ai-parrot/src/parrot/knowledge/pageindex/
class JSONTreeStore            # store.py:23 — list_names, exists, load, save, delete, rename
class NodeContentStore         # content_store.py:38 — save, load, has, delete_node, delete_tree, rename_tree, list_node_ids, loader_for
class NodeEmbeddingStore       # embedding_store.py:42 — content_key, get_or_embed, build_tree_matrix, load_tree_matrix, invalidate_tree
class HybridPageIndexSearch    # hybrid_search.py:73 — _rebuild_bm25 :163, _bm25_rank :177, _vec_rank :199, _llm_rank :265, _rrf_fuse :277, search :288
# toolkit.py:114-133 instantiates JSONTreeStore / NodeContentStore / NodeEmbeddingStore
# From packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py:163
class CatalogStore:   # sync sqlite3; supports_fts :269, upsert :300, remove, get, find_by_sha, find_by_path, list_cards, search(query, top_k=8) :409,
                      # upsert_relations :496, delete_relations, list_relations, record_judgements, upsert_communities :680, set_card_community :730
# library.py:230 — self._catalogs[scope] = CatalogStore(self._location(scope).db_path); search_book :351; search :411
```

```python
# From packages/ai-parrot/src/parrot/_imports.py:110
def lazy_import(module_path: str, package_name: str | None = None, extra: str | None = None) -> ModuleType
```

```toml
# From ruff.toml:113,125-127,155-163
select = ["E4", "E7", "E9", "F", "TID251", "B", "ASYNC", "PIE", "C4", "LOG"]
[lint.flake8-tidy-imports.banned-api]
"httpx".msg = "Use aiohttp — httpx is banned in this repository."
# per-file-ignores already exempt e.g. "packages/ai-parrot/src/parrot/interfaces/http.py" = ["TID251"]
# From packages/ai-parrot/pyproject.toml:273-290 — extras `graphindex`, `graphindex-postgres = ["asyncpg>=0.29", "pgvector>=0.2"]`
# From pyproject.toml:265 / packages/ai-parrot/pyproject.toml:1045-1047 — markers real_llm, network, live
```

#### Verified HelixDB SDK surface (helix-db 0.3.4 / helix-db-embedded 0.3.3, read from the unpacked wheels)
```python
# helixdb/__init__.py — exports AsyncClient, AsyncQueryBuilder, Client, Disk, InMemory, ObjectStorage,
#   EmbeddedCacheConfig, HybridCache, MemoryCache, VectorMemoryOnly, HelixDbSource, HelixError, QueryBuilder,
#   QueryExecutionRequest, dsl.*, graph.* (NativeGraph, LeidenOptions, LouvainOptions, BetweennessOptions, ...)
# helixdb/async_client.py
class AsyncClient:
    def __init__(self, url: str | None = None, *, api_key=None, timeout=None, limits: httpx.Limits | None = None, transport=None)
    @classmethod async def embedded(cls, source: HelixDbSource, *, cache: EmbeddedCacheConfig | None = None) -> AsyncClient
    @classmethod async def embedded_reader(cls, source, *, cache=None) -> AsyncClient
    def with_api_key(self, api_key) ; def request_builder(self) -> AsyncQueryBuilder
    async def query(self, request: QueryRequest, *, timeout=None) -> Any
    async def execute(self, request: QueryRequest, **options) -> Any      # writer_only / warm_only / timeout (server only)
    async def close(self) -> None ; async __aenter__/__aexit__
# helixdb/_client_common.py: QUERY_PATH = "/v2/query"; class HelixError(Exception) with .network/.remote/.embedded/.embedded_unavailable
# helixdb/client.py:161-206: @dataclass(frozen=True) class InMemory(database: str); class Disk(root: str, database: str);
#   class ObjectStorage(...); EmbeddedCacheConfig; _native_helixdb() lazily imports helixdb_uniffi (:281)
# helixdb/dsl.py: read_batch() :3410, write_batch() :3414, g() :3054, sub() :3170, define_params :3657, QueryRequest :3861,
#   IndexSpec :1284 (node_equality, node_unique_equality, node_range, node_text, node_vector, edge_*),
#   Predicate :770, BatchCondition :3175 (var_not_empty, var_empty, var_min_size), ReadBatch.var_as_if :3271, WriteBatch.var_as_if :3358,
#   VectorDistanceMetric :592 (COSINE/...), Traversal methods include: n, n_where, n_with_label, n_with_label_where, e, e_with_label,
#   out, in_, both, out_e, in_e, both_e, add_n, add_e, set_property, remove_property, drop, drop_edge, drop_edge_by_id, drop_edge_labeled,
#   create_index, create_index_if_not_exists, drop_index, get_index_operation, abort_index_operation, retry_index_operation,
#   create_text_index_nodes/edges, create_vector_index_nodes/edges, text_search_nodes/edges(+_with/_within), vector_search_nodes/edges(+_with/_within),
#   where, limit, skip, order_by, dedup, count, value_map, project, shortest_path, repeat, group_count, aggregate_by, union, for_each
# helixdb_uniffi/helixdb.py (embedded): class HelixDbSource (IN_MEMORY(database) :3544, DISK(root, database)), class HelixDb :5560
#   with async open/open_reader/open_with_config, async query_json(request: bytes) -> bytes, async graph(request, spec), async close()
```

#### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, WikiPageRecord, register_wiki_backend, create_wiki_store  # wiki/store.py
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiNamespaceConfig, resolve_arango_params, sqlite_policy_from_config
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.publish import GraphPublisher
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit, make_stub_tenant_context, HashingGraphEmbedder
from parrot.knowledge.graphindex.schema import UniversalNode, UniversalEdge, GraphUpdate, CommitReceipt, AssertionMeta
from parrot.knowledge.ontology.schema import TenantContext, MergedOntology
from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch
from parrot.knowledge.bookstore.catalog import CatalogStore
from parrot._imports import lazy_import
# external (after `uv add --optional helixdb helix-db==0.3.4`):
from helixdb import AsyncClient, Disk, InMemory, IndexSpec, Predicate, VectorDistanceMetric, g, read_batch, write_batch
```

#### Key Attributes & Constants
- `SCHEMA_VERSION = "3"` (wiki/store.py:51) — HelixDB `Meta` node must record the same key for lint parity.
- `WikiProjectConfig.body_max_chars` default `16_000` (project.py:608) — bound for `search_text`.
- `DEFAULT_DIMENSION = 256` (graphindex/factory.py:41) — candidate default vector dimension for GraphIndex.
- `helixdb._client_common.QUERY_PATH = "/v2/query"`; server image `ghcr.io/helixdb/helixdb:v0.0.12` listens on container port 8080, published as 6969; `/healthz`, `/readyz`; env `HELIX_DATA_DIR` (disk) or `S3_BUCKET` (object store), never both; runs as uid/gid 65532.
- HelixDB limits (docs, 2026-10): whole-index search result cap 800; per-document text analysis 64 MiB / ~16k unique terms; queued index work per write 8 MiB; text/vector indexes require **top-level** string / numeric-array properties; one label per node; node and edge ids are u64 from separate sequences; unique indexes only on node equality indexes.
- Python SDK 0.3.4 cannot set `search_consistency` (server default is `strong`).

### Does NOT Exist (Anti-Hallucination)
- ~~HelixQL `.hx` schema/query files, `helix compile` / `helix deploy`~~ — legacy (pre-v3) workflow; the current generation sends JSON operation trees to `POST /v2/query` with no build step.
- ~~`helixdb.upsert` / `g().upsert(...)`~~ — no upsert operation; emulate with lookup + `set_property` / `add_n` inside one write batch.
- ~~`AsyncClient.graph()`~~ — native graph algorithms exist only on the sync `Client.graph(selection)`.
- ~~`AsyncClient.cypher()` / `QueryRequest.cypher`~~ — no Cypher in the Python SDK 0.3.4; `/v2/cypher` is documented for source builds only.
- ~~`SearchConsistency` on Python 0.3.4 requests~~ — docs state it ships in SDK releases after 0.3.4.
- ~~`parrot.knowledge.helix`, `HelixWikiStore`, `HelixPersistence`, `HelixOntologyGraphStore`, `HELIXDB_URL`, `create_wiki_store(backend="helixdb")`~~ — all to be created by this feature.
- ~~A `BasePersistence` ABC for GraphIndex backends~~ — persistence is duck-typed (`GraphPublisher.__init__(persistence: Any)`); the new backend mirrors `SQLitePersistence`'s method set.
- ~~`BaseWikiStore.close()` / `initialize()` abstract methods~~ — only `ArangoDBWikiStore` / `PostgresPersistence` define them; consumers do not call them generically.
- ~~A SQLite-backed PageIndex~~ — PageIndex stores JSON + markdown + `.npy`; no `pageindex/*.db`.
- ~~A HelixDB driver in `asyncdb`~~ — none; the provider uses `helix-db` directly.
- ~~`docker/helixdb/`, Makefile `docker-helixdb` / `helixdb-*` targets, `ai-parrot[helixdb]` extra~~ — to be created.
- ~~`WikiNamespaceConfig.backend` Literal including `"helixdb"`~~ — today the field is free-form for satellite backends; `"helixdb"` must be added to the built-in set documented at project.py:205-210.

---

## Parallelism Assessment

- **Internal parallelism**: high after a short serial head. M0 (`parrot/knowledge/helix/` client + bootstrap, extras, ruff exemption, docker, Makefile) must land first. Then M1 wiki store, M3 GraphIndex persistence, M4 ontology store, M5a PageIndex projection and M5b BookStore projection touch disjoint files and can run in parallel sub-worktrees. M2 (ledger/schema) depends on M1. Config/CLI Literal edits (`models.py`, `project.py`, `cli.py`, `sources.py`) should be one exclusive task to avoid three-way conflicts. The parity test suite (M6) is last.
- **Cross-feature independence**: conflicts with **FEAT-540 graphindex-core-seams** (13 pending tasks; TASK-3266 relocates `GraphIndexLoader`, TASK-3267 moves the `OntologyGraphStore` import in `graphindex/persist.py`, TASK-3257 lazy ontology package roots), **FEAT-633 parrot-installer** (TASK-4092/4093 edit `wiki/store.py:1107-1497` and `project.py:38-110`), and FEAT-481 fireflies wiki (16 open tasks on wiki ingest). The user chose to proceed and reconcile at merge time; the spec must list these as merge-time checks.
- **Recommended isolation**: `mixed`.
- **Rationale**: the shared head (M0 + config Literals) is small and sequential; the per-plane backends are independent modules with their own tests, so sub-worktrees shorten wall-clock without touching the same files.

---

## Open Questions

All resolved on 2026-10-14 (review round after the brainstorm was committed).

- [x] **Vector index dimension strategy** — `upsert_embedding(vector, model)` is dimension-agnostic today; HelixDB fixes the dimension at index creation. — *Owner: Jesus Lara*: lazy per-dimension index. The first vector written for a label creates the property `embedding_<dim>` and its cosine vector index; a later vector of another length creates a sibling property/index; `search_vector()` selects the index matching the query vector's length. No new config field.
- [x] **Makefile "embedded" target semantics** — *Owner: Jesus Lara*: dropped. Only `make docker-helixdb` (server) is added; embedded stays a test fixture with no Makefile entry.
- [x] **Cypher availability** — *Owner: Jesus Lara*: out of scope, never probed. Typed traversal methods on `OntologyGraphStore` are mandatory; ArangoDB keeps AQL inside them, HelixDB uses the DSL. Option D is recorded for history only.
- [x] **Multi-process embedded `Disk` behaviour** — *Owner: implementer (M0)*: keep a 30-minute spike in M0 whose only output is the observed error class when a second process opens a writer, used to word the `helix_mode=embedded` guard message and the docs. No design decision depends on it.
- [x] **`LedgerStore.ledger_transaction()` reshaping** — *Owner: Jesus Lara*: hard cut. `ledger_transaction()` yields a backend-neutral `LedgerTxn` accumulator (`upsert_pages`, `add_edges`, `set_state`); the SQLite implementation wraps the connection, the HelixDB one collects a single `write_batch`. All 10 call sites in `wiki/ledger/` are updated in-feature, no shim.
- [x] **CI native wheel** — *Owner: Jesus Lara*: install `helix-db-embedded` in CI (test extras / uv dev group); unit tests run on embedded `InMemory` on every PR. Live server tests stay gated on `HELIXDB_URL` reachability.
- [x] **Tenancy mapping for GraphIndex** — *Owner: Jesus Lara*: one HelixDB database per tenant — server database `gi_<tenant>`, embedded `Disk(root, tenant)`. Mirrors `<tenant>.db` and ArangoDB's `db_<tenant>`; no `tenant_id` filters in queries.
- [x] **ArangoDB retirement** — *Owner: Jesus Lara*: there is no retirement. HelixDB is an additional supported backend; `ArangoDBWikiStore`, `GraphIndexPersistence` (ArangoDB) and `docker/arango` stay first-class, with no deprecation warnings or doc pointers away from them.
- [x] **Server image pin and upgrade policy** — *Owner: Jesus Lara*: compose reads `${HELIXDB_IMAGE_TAG:-v0.0.12}`; the `docker/helixdb/README.md` documents the one-way index-storage-version upgrade and a manual `HELIX_DATA_DIR` volume backup (`docker run --rm -v helixdb-data:/data … tar`) to run before changing the tag. Bumping the default tag is a reviewed manual change; no Makefile backup target.
