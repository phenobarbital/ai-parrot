<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

### Constraints and goals
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

### Recommended option / probable scope
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

### Verified code anchors (paths only — open them yourself)
Makefile
docker/helixdb/
packages/ai-parrot/pyproject.toml
packages/ai-parrot/src/parrot/_imports.py
packages/ai-parrot/src/parrot/interfaces/http.py
packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py
packages/ai-parrot/src/parrot/knowledge/graphindex/communities.py
packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py
packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py
packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py
packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py
packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py
packages/ai-parrot/src/parrot/knowledge/graphindex/publish.py
packages/ai-parrot/src/parrot/knowledge/graphindex/schema.py
packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py
packages/ai-parrot/src/parrot/knowledge/ontology/schema.py
packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py
packages/ai-parrot/src/parrot/knowledge/wiki/federation.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py
packages/ai-parrot/src/parrot/knowledge/wiki/models.py
packages/ai-parrot/src/parrot/knowledge/wiki/postgres_store.py
packages/ai-parrot/src/parrot/knowledge/wiki/project.py
packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py
packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py
packages/ai-parrot/src/parrot/knowledge/wiki/sources.py
packages/ai-parrot/src/parrot/knowledge/wiki/store.py
ruff.toml

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
