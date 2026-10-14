---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools, ci]
tags: [helixdb, graph-database, wiki, graphindex, vector-search, bm25]
---

# Feature Specification: HelixDB graph provider

**Feature ID**: FEAT-670
**Date**: 2026-10-14
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 1.3.0
**Source brainstorm**: `sdd/proposals/helixdb-provider.brainstorm.md` (accepted 2026-10-14; Option A; 9 resolved questions)

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot keeps **five local knowledge planes on SQLite** and **two shared planes on
ArangoDB**, each with its own hand-rolled graph / FTS / vector emulation:

| Plane | Today | Shape |
|---|---|---|
| LLM Wiki retrieval plane | `SQLiteWikiStore` (`wiki.db`, FTS5, `embeddings` blob table) / `ArangoDBWikiStore` / `PostgresWikiStore` | pages + edges + symbols + attrs + meta behind `BaseWikiStore` |
| GraphIndex graph memory | `SQLitePersistence` (`<tenant>.db`, `nodes_fts`) / `GraphIndexPersistence` (ArangoDB) / `PostgresPersistence` | nodes + edges + files + commit protocol |
| SDD work ledger | `LedgerStore(SQLiteWikiStore)` (`ledger.db`) | wiki plane + `ledger_state` + composable `aiosqlite` transactions |
| SQL schema overlay | `SchemaStore(SQLiteWikiStore)` (`schema.db`) | wiki plane + `columns` table |
| BookStore catalog | `CatalogStore` (sync `sqlite3`, `books_fts`) | cards + relations + judgements + communities |
| PageIndex | `JSONTreeStore` + `NodeContentStore` (.md) + `NodeEmbeddingStore` (.npy) — **not SQLite** | tree + bodies + embedding matrix; hybrid search = `bm25s` + numpy + LLM walk |
| Ontology graph | `OntologyGraphStore` (ArangoDB, raw AQL) | per-tenant vertex/edge collections + ArangoSearch views |

Graph traversal on the SQLite planes is emulated with `edges` tables and in-memory
`rustworkx` rebuilds, BM25 with FTS5, vectors with brute-force numpy over blob columns.
The shared variant needs a separate ArangoDB deployment with a second code path (AQL)
per plane.

**HelixDB** (Apache 2.0, Rust) is a labeled-property-graph database with native vector
(cosine / euclidean / manhattan) and BM25 text indexes in one transactional engine,
usable **embedded in-process** (`helix-db-embedded`: InMemory / Disk / S3) or as a
**server** (`ghcr.io/helixdb/helixdb:v0.0.12`, `POST /v2/query`). Since the v3
generation there is **no compile/deploy step**: queries are JSON operation trees built by
the Python DSL at runtime, so one backend implementation serves both the local and the
shared deployment. This feature adds a `helixdb` backend to every plane above, selected
by configuration, with every existing backend untouched.

### Goals

- **G1** `HelixWikiStore(BaseWikiStore)` at functional parity with `SQLiteWikiStore` (pages, edges, FTS, vectors, symbols, attrs, meta, CAS, lint methods), selectable as `backend: helixdb` everywhere a backend is chosen today (config, CLI, env, namespaces, `SourceCollectionManager`).
- **G2** `HelixPersistence` for GraphIndex mirroring the `SQLitePersistence` surface **including the commit protocol** (`apply_update` / `get_commit` / `list_commits` / `revert_commit`), wired into every instantiation site.
- **G3** Ledger and schema-overlay planes on HelixDB, via a backend-neutral `LedgerTxn` accumulator (hard cut of `ledger_transaction()`).
- **G4** `HelixOntologyGraphStore` with the `OntologyGraphStore` method surface, after the eight raw-AQL call sites move behind typed traversal methods.
- **G5** PageIndex and BookStore **projections**: files / SQLite stay canonical, HelixDB serves BM25 + vector ranking and graph edges when configured.
- **G6** One shared client/bootstrap module: server (`HELIXDB_URL`) or embedded (`Disk` / `InMemory`), readiness probe, idempotent label/index bootstrap with receipt polling, lazy per-dimension vector indexes.
- **G7** Infra: `docker/helixdb/` (compose, `HELIXDB_IMAGE_TAG`, `HELIX_DATA_DIR` volume, `/readyz`, backup-before-upgrade README), `make docker-helixdb`, extras `ai-parrot[helixdb]` / `ai-parrot[helixdb-embedded]`, CI installs the embedded wheel.
- **G8** The local multi-process workflow (post-commit hook + MCP server + parallel sessions) is served by the **server** mode; embedded mode is for tests and single-process tools only.
- **G9** `httpx` is confined to one module (`parrot/knowledge/helix/client.py`) under a per-file `TID251` exemption and used only through `helixdb.AsyncClient`.

### Non-Goals (explicitly out of scope)

- Retiring, deprecating or redirecting away from ArangoDB — HelixDB is an **additional** peer backend; `ArangoDBWikiStore`, `GraphIndexPersistence`, `docker/arango` are unchanged (resolved Q8).
- Cypher (`/v2/cypher`) — never probed, never used; typed traversals are mandatory (resolved Q3). Brainstorm Option D is history only.
- A Makefile target for embedded mode (resolved Q2).
- A satellite distribution `ai-parrot-helixdb` (brainstorm Option B, rejected by the user).
- Full relocation of PageIndex / BookStore into HelixDB (brainstorm Option C "full relocation" variant) — projection only.
- Helix Cloud, S3/object-storage sources, `ObjectStorage` embedded source — not wired (server + Disk + InMemory only).
- Waiting for FEAT-540 / FEAT-633 — the user chose to proceed now and reconcile at merge time.
- Changing `SQLiteWikiStore`, `SQLitePersistence` or any existing backend's behaviour.

---

## 2. Architectural Design

### Overview

One new package, `parrot/knowledge/helix/`, owns everything HelixDB-specific that is
plane-independent: **settings resolution** (`HELIXDB_URL`, `HELIXDB_API_KEY`,
`HELIXDB_MODE`), **client opening** (server `AsyncClient(url)` after an `aiohttp` probe of
`/readyz`; embedded `AsyncClient.embedded(Disk|InMemory)` / `embedded_reader`),
**bootstrap** (idempotent label/index DDL issued as `create_*_index*` entries and
receipt-polled via `get_index_operation` until active), **DSL helpers** (unique-key
lookup, find-or-add edge, lazy vector index by dimension, text search projection) and
**error mapping** (`HelixError` → `HelixUnavailable` / `HelixWriteRejected`).

Every plane then gets a backend class that speaks only to that package:

| Plane | Backend | Seam that gains `"helixdb"` |
|---|---|---|
| Wiki | `wiki/helix_store.py: HelixWikiStore(BaseWikiStore)` | `create_wiki_store()`, `WikiConfig.storage_backend`, `WikiProjectConfig.backend`, `WikiNamespaceConfig.backend`, CLI `--backend`, `WIKI_STORE_BACKEND`, `SourceCollectionManager(backend=…)` |
| Ledger | `wiki/ledger/helix_store.py: HelixLedgerStore` + `LedgerTxn` protocol | `LedgerService.from_root/from_dir` |
| Schema overlay | `wiki/schema/helix_store.py: HelixSchemaStore` | `SchemaPlaneService.from_root/from_dir` |
| GraphIndex | `graphindex/persist_helix.py: HelixPersistence` | `build_graph_memory_toolkit(backend=…)`, `GraphIndexLoader._make_persistence()`, `wiki/runtime.py`, `wiki/cli.py` (4 sites), `flows/dev_loop/graph_memory.py` |
| Ontology | `ontology/helix_graph_store.py: HelixOntologyGraphStore` | `GraphIndexLoader`, `parrot_tools/graphindex/flowtask.py`, `parrot_tools/legal/{wiki_store,boe/sync}.py` |
| PageIndex | `pageindex/helix_projection.py: PageIndexHelixProjection` | `PageIndexToolkit.__init__`, `HybridPageIndexSearch` |
| BookStore | `bookstore/helix_projection.py: BookstoreHelixProjection` | `Library._catalogs`, `CatalogStore.search` |

**Data-model mapping (normative):**

- One **label per record kind**: `Page`, `Symbol`, `Source`, `Meta`, `PageAttr`, `GNode`,
  `GFile`, `GCommit`, `GCommitItem`, `Column`, `TreeNode`, `Book`, `BookCommunity`, and
  the ontology entity labels. HelixDB node ids are u64 sequences, so every user key
  (`concept_id`, `node_id`, `source_id`, `book_id`, `(rel_path, name)` for symbols) is a
  **unique equality index** property and all lookups use `n_where(Predicate.eq(...))`.
- **Edges** keep `(src, dst, rel, provenance)` as `rel`-labelled edges with properties.
  SQLite's `INSERT OR REPLACE` on `(src, dst, rel)` becomes "find via `out_e(rel)` filtered
  on target else `add_e`" inside one write batch (HelixDB is a multigraph, it never dedupes).
- **FTS**: `pages_fts` (multi-column FTS5) becomes one BM25 text index on a top-level
  `search_text` property (title + summary + body, truncated to `body_max_chars`), queried
  with `text_search_nodes("Page", "search_text", q, k)` and projected with `$score`.
  `symbols_fts` likewise on `Symbol.search_text`; GraphIndex `nodes_fts` on `GNode.search_text`.
- **Vectors**: lazy per-dimension indexes (resolved Q1). The first vector of length *d*
  written for a label creates property `embedding_<d>` and a cosine vector index on it;
  the bootstrap records known dimensions in the `Meta` node `vector_dims:<label>`;
  `search_vector()` selects the index whose dimension equals the query length and returns
  `[]` with a warning when none matches.
- **Transactions**: every `BaseWikiStore` write is one `write_batch` (atomic);
  `replace_source_slice` = drop slice + add; `compare_and_swap_page` = conditional entries
  (`var_as_if(BatchCondition.var_empty/var_not_empty)`) on a `content_hash` predicate.
  Reads use the server default `strong` search consistency (read-after-write safe).
- **Tenancy**: one HelixDB **database per tenant** for GraphIndex (server `gi_<tenant>`,
  embedded `Disk(root, tenant)`; resolved Q7); one database per wiki
  (`wiki_<wiki_name>`), per ledger (`ledger_<wiki_name>`), per schema plane
  (`schema_<wiki_name>`), per ontology tenant (`ont_<tenant>`).
- **Meta**: a `Meta` node per key mirrors SQLite's `meta` table, including
  `schema_version = "3"` so lint parity holds.

**Deployment modes:**

- `helix_mode: server` (default): `HELIXDB_URL` (default `http://127.0.0.1:6969`),
  optional `HELIXDB_API_KEY`; readiness probe `GET /readyz` through `aiohttp` with a
  bounded retry before the first query; the post-commit hook path fails soft (log + exit 0)
  when the server is unreachable, like `WikiStoreBusy` today.
- `helix_mode: embedded`: `Disk(<storage_dir>/helix, <database>)`; refused when another
  process holds `wiki.lock` (`project.wiki_write_lock`) with a message pointing to server
  mode; `InMemory(<database>)` for tests. The M2 spike documents the exact error class a
  second embedded writer sees (resolved Q4, wording only).

**Infra:** `docker/helixdb/docker-compose.yml` runs `ghcr.io/helixdb/helixdb:${HELIXDB_IMAGE_TAG:-v0.0.12}`
with a named `helixdb-data` volume at `HELIX_DATA_DIR=/var/lib/helix`, port
`${HELIXDB_PORT:-6969}:8080`, `/readyz` healthcheck, user 65532; the README documents the
one-way index-storage-version upgrade and the manual volume backup before a tag bump
(resolved Q9). `make docker-helixdb` wraps `docker compose up -d` (resolved Q2: no embedded
target). Extras: `helixdb = ["helix-db==0.3.4"]`, `helixdb-embedded = ["ai-parrot[helixdb]", "helix-db-embedded==0.3.3"]`;
the root `dev` dependency group gains `helix-db` + `helix-db-embedded` so `uv sync --all-packages`
in CI runs the embedded unit tier on every PR (resolved Q6).

### Component Diagram

```
                 ┌──────────────── parrot/knowledge/helix/ ────────────────┐
                 │ settings.py  client.py  bootstrap.py  dsl.py  errors.py │
                 │   (HELIXDB_*)  (AsyncClient server|embedded, /readyz)    │
                 └───────┬──────────┬──────────┬──────────┬──────────┬─────┘
                         │          │          │          │          │
   wiki/helix_store.py   │  graphindex/persist_helix.py   │  ontology/helix_graph_store.py
   HelixWikiStore ───────┘  HelixPersistence ─────────────┘  HelixOntologyGraphStore
        │  ▲                        ▲                                 ▲
        │  │ composes               │ duck-typed                      │ typed traversals
 ledger/helix_store.py       GraphPublisher / factory /         authorization.py
 HelixLedgerStore (LedgerTxn) loader / runtime / cli            entity_resolver.py  mixin.py
 schema/helix_store.py
 HelixSchemaStore
        │
 pageindex/helix_projection.py   bookstore/helix_projection.py
 (TreeNode + CHILD_OF, BM25/vec)  (Book + RELATES_TO, communities)
        ▲                                ▲
 HybridPageIndexSearch            CatalogStore.search / Library

 docker/helixdb/ (server, HELIXDB_IMAGE_TAG, HELIX_DATA_DIR)  ◄── HELIXDB_URL ── every process
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `create_wiki_store()` (`wiki/store.py:2665`) | extends | new `backend == "helixdb"` branch before `_EXTRA_BACKENDS`, lazy import of `helix_store` |
| `WikiConfig.storage_backend` (`wiki/models.py:114`), `WikiProjectConfig.backend` (`project.py:605`) | modifies | Literals gain `"helixdb"`; new fields `helix_database`, `helix_credentials_env`, `helix_mode` next to the `arango_*` fields |
| `WikiNamespaceConfig` (`project.py:186`) | modifies | `"helixdb"` becomes a built-in `database`-kind backend (doc at `:205-210`); `open_namespace_store` (`federation.py:362`) dispatches it |
| `wiki/cli.py` `--backend` choices (`:670`, `:1520`), `entity_cli.py` | modifies | `click.Choice` lists gain `"helixdb"` |
| `SourceCollectionManager` (`wiki/sources.py:148`, `:184`) | extends | fourth backend `"helixdb"` (`Source` nodes), mirroring the `arangodb` async branch via `_run_async` |
| `LedgerStore` (`ledger/store.py:24`), `LedgerService` (`ledger/service.py:140,164`), `ledger/index.py`, `ledger/sdd_ingest.py` | modifies (hard cut) | `ledger_transaction()` yields `LedgerTxn`; 9 call sites rewritten; service dispatches on `WikiProjectConfig.backend` |
| `SchemaStore` (`schema/store.py:48`), `SchemaPlaneService` (`schema/service.py:66,82`) | extends | `HelixSchemaStore`; service dispatch |
| `build_graph_memory_toolkit` (`graphindex/factory.py:197`) | extends | `backend == "helixdb"` branch (lazy import) with `helix_url` / `helix_source` kwargs |
| `GraphIndexLoader._make_persistence` (`loader.py:288`) | extends | `helix_params` constructor kwarg → `HelixPersistence` |
| `wiki/runtime.py:91`, `wiki/cli.py:4011,4108,4561,4623`, `flows/dev_loop/graph_memory.py:142` | modifies | one shared resolver `graphindex_persistence_for(config, root)` replaces direct `SQLitePersistence(...)` |
| `GraphPublisher` (`publish.py:37`) | uses | duck-typed persistence, unchanged |
| `OntologyGraphStore` (`ontology/graph_store.py:53`) | modifies | typed traversal methods added; `execute_traversal()` demoted to a private ArangoDB helper |
| `ontology/authorization.py:257,339`, `entity_resolver.py:384,427`, `mixin.py:337,359,379` | modifies | call the typed methods |
| `parrot_tools/graphindex/flowtask.py:220`, `parrot_tools/legal/wiki_store.py`, `parrot_tools/legal/boe/sync.py` | modifies | graph-store factory `ontology_graph_store_for(backend, …)` |
| `PageIndexToolkit.__init__` (`pageindex/toolkit.py:114-133`), `HybridPageIndexSearch` (`hybrid_search.py:163-263`) | extends | optional `helix_projection` injection; `_bm25_rank` / `_vec_rank` delegate when present |
| `Library` (`bookstore/library.py:230`), `CatalogStore` (`catalog.py:163`) | extends | optional projection; `search()` delegates when present |
| `packages/ai-parrot/pyproject.toml:287`, root `pyproject.toml` dev group, `ruff.toml:163`, `.github/workflows/ci.yml:27` | modifies | extras, dev wheel, TID251 per-file ignore, CI unchanged command now installs the wheel via the dev group |
| `Makefile:920`, `:1097`, `docs/wiki/cheatsheet.md:43` | modifies | `docker-helixdb` target + help line + docs |

### Data Models

```python
# parrot/knowledge/helix/settings.py (new)
class HelixMode(str, Enum):
    SERVER = "server"
    EMBEDDED = "embedded"
    MEMORY = "memory"          # tests only

class HelixSettings(BaseModel):
    """Resolved connection settings for one HelixDB database."""
    mode: HelixMode = HelixMode.SERVER
    url: str = "http://127.0.0.1:6969"          # server mode
    api_key: str | None = None                   # server mode
    root: Path | None = None                     # embedded Disk root
    database: str                                # logical database name
    read_only: bool = False
    probe_timeout_s: float = 5.0
    probe_retries: int = 3
    index_ready_timeout_s: float = 120.0

class LabelSpec(BaseModel):
    """Declarative per-label bootstrap: unique key, equality indexes, text property."""
    label: str
    unique_key: str
    equality: list[str] = []
    text_property: str | None = None          # "search_text"
    vector_property_prefix: str | None = None  # "embedding" → embedding_<dim>

class PlaneSchema(BaseModel):
    """All labels and edge labels one plane bootstraps."""
    plane: str                                   # "wiki" | "ledger" | "schema" | "graphindex" | "ontology" | "pageindex" | "bookstore"
    schema_version: str                          # mirrors SQLite SCHEMA_VERSION ("3" for wiki)
    labels: list[LabelSpec]
    edge_labels: list[str]
```

### New Public Interfaces

```python
# parrot/knowledge/helix/__init__.py (new)
from parrot.knowledge.helix.settings import HelixSettings, HelixMode, resolve_helix_settings
from parrot.knowledge.helix.client import HelixClient, open_helix_client
from parrot.knowledge.helix.bootstrap import PlaneSchema, LabelSpec, ensure_plane
from parrot.knowledge.helix.errors import HelixUnavailable, HelixWriteRejected, HelixExtraMissing

# wiki
from parrot.knowledge.wiki.helix_store import HelixWikiStore
from parrot.knowledge.wiki.ledger.store import LedgerTxn               # protocol (hard cut)
from parrot.knowledge.wiki.ledger.helix_store import HelixLedgerStore
from parrot.knowledge.wiki.schema.helix_store import HelixSchemaStore
# graphindex
from parrot.knowledge.graphindex.persist_helix import HelixPersistence
from parrot.knowledge.graphindex.persistence_resolver import graphindex_persistence_for
# ontology
from parrot.knowledge.ontology.graph_store import OntologyGraphStore   # + typed traversal methods
from parrot.knowledge.ontology.helix_graph_store import HelixOntologyGraphStore
from parrot.knowledge.ontology.factory import ontology_graph_store_for
# projections
from parrot.knowledge.pageindex.helix_projection import PageIndexHelixProjection
from parrot.knowledge.bookstore.helix_projection import BookstoreHelixProjection
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: helix client, settings, bootstrap, extras | no | — | the DSL helper layer (find-or-add edge, lazy vector index, receipt polling) is the design every other module depends on; thinking model owns it |
| M2: docker/helixdb + Makefile + docs + spike | yes | compose shape fixed in §2 (image tag var, volume, port, healthcheck, uid 65532); Makefile target shape = `docker-dev` precedent; README sections fixed in §7 | — |
| M3: HelixWikiStore + sources backend | yes | `BaseWikiStore` contract verbatim; label map and batch shapes in §2; parity tests are the existing CAS/attrs/symbols suites | — |
| M4: config / CLI selection surface | yes | exact Literal values, field names and defaults in §3 M4 skeleton; `click.Choice` lists | — |
| M5: Ledger hard cut + HelixLedgerStore | no | — | `LedgerTxn` protocol shape is fixed here, but rewriting `index.py` replay/compact logic over it needs judgement |
| M6: HelixSchemaStore | yes | `Column` node + `COLUMN_OF` edge; same method surface as `SchemaStore` (§6) | — |
| M7: HelixPersistence + resolver | no | — | commit-protocol revert ordering over batches is the one algorithmic piece; keep with thinking model |
| M8: Ontology typed traversals + Helix store | no | — | touches authorization (security-sensitive); traversal method semantics must be derived from the existing AQL |
| M9: PageIndex projection | yes | `TreeNode` + `CHILD_OF`; delegation points `_bm25_rank` / `_vec_rank` (§3 M9) | — |
| M10: BookStore projection | yes | `Book` + `RELATES_TO` + `BookCommunity`; `search()` delegation (§3 M10) | — |
| M11: parity + live test suites, docs | yes | test file list and skip gates fixed in §4 | — |

### Module 1: HelixDB client, settings, bootstrap, DSL helpers, extras

- **Path**: `packages/ai-parrot/src/parrot/knowledge/helix/{__init__,settings,client,bootstrap,dsl,errors}.py` (new); `packages/ai-parrot/pyproject.toml` (extras); root `pyproject.toml` (dev group); `ruff.toml` (per-file ignore)
- **Responsibility**: the only HelixDB-SDK-facing code. Settings resolution via the `_env_credential` chain, server/embedded client opening with readiness probe, idempotent plane bootstrap with receipt polling, DSL helpers shared by every backend, error mapping, optional-extra guard via `lazy_import`.
- **Depends on**: `helix-db==0.3.4` (extra), `helix-db-embedded==0.3.3` (extra, lazily), `parrot._imports.lazy_import`, `parrot.knowledge.wiki.project._env_credential`
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/helix/errors.py (new)
  class HelixExtraMissing(ImportError):
      """Raised when `helixdb` (or `helixdb_uniffi` for embedded) is not installed; message names the extra."""
  class HelixUnavailable(RuntimeError):
      """Server not reachable / not ready after the bounded probe, or embedded source refused."""
  class HelixWriteRejected(RuntimeError):
      """A write batch was rejected (e.g. active_text_mutation_limit_exceeded); carries the offending key."""

  # parrot/knowledge/helix/settings.py (new)
  def resolve_helix_settings(
      *, database: str, credentials_env: str = "HELIXDB", mode: str | None = None,
      storage_dir: Path | None = None, read_only: bool = False,
  ) -> HelixSettings:
      """Resolve HELIXDB_URL / HELIXDB_API_KEY / HELIXDB_MODE through `_env_credential`
      (os.environ → navconfig → default)  # _env_credential verified: wiki/project.py:822
      Embedded modes require `storage_dir` (Disk root = storage_dir / "helix")."""

  # parrot/knowledge/helix/client.py (new) — the ONLY module exempted from TID251; imports helixdb only
  class HelixClient:
      """Thin async wrapper over `helixdb.AsyncClient` with uniform error mapping."""
      settings: HelixSettings
      async def read(self, batch: "ReadBatch", *, query_name: str) -> dict[str, Any]:
          """Execute a read batch; returns the `returning` map; raises HelixUnavailable on transport errors."""
      async def write(self, batch: "WriteBatch", *, query_name: str) -> dict[str, Any]:
          """Execute an atomic write batch; raises HelixWriteRejected on 400-class rejections, PermissionError when read_only."""
      async def close(self) -> None: ...
      async def __aenter__(self) -> "HelixClient": ...
      async def __aexit__(self, *exc: object) -> None: ...

  async def open_helix_client(settings: HelixSettings) -> HelixClient:
      """Server: aiohttp GET {url}/readyz with `probe_retries` × `probe_timeout_s`, then AsyncClient(url, api_key=…).
      Embedded: AsyncClient.embedded(Disk|InMemory) or embedded_reader when read_only.
      Raises HelixExtraMissing / HelixUnavailable."""

  # parrot/knowledge/helix/bootstrap.py (new)
  async def ensure_plane(client: HelixClient, schema: PlaneSchema) -> dict[str, Any]:
      """Issue create_index_if_not_exists / create_text_index_nodes for every LabelSpec in ONE write batch,
      poll get_index_operation until active or `index_ready_timeout_s`, upsert Meta(schema_version).
      Returns {"created": [...], "active": [...], "blocked": [...]}; raises HelixUnavailable on blocked builds."""
  async def ensure_vector_index(client: HelixClient, label: str, prefix: str, dimension: int) -> str:
      """Lazy per-dimension index (resolved Q1): returns the property name `{prefix}_{dimension}`,
      creating property index on first use and recording it in Meta `vector_dims:<label>`."""
  async def known_vector_dimensions(client: HelixClient, label: str) -> list[int]: ...

  # parrot/knowledge/helix/dsl.py (new) — pure builders, no I/O
  def lookup_by_key(label: str, key: str, value: Any) -> "Traversal":
      """g().n_where(Predicate.eq(key, value)) restricted to `label`."""
  def upsert_node_entries(batch: "WriteBatch", var: str, label: str, key: str, props: Mapping[str, Any]) -> "WriteBatch":
      """Conditional entries: var_as_if(var_empty → add_n, var_not_empty → set_property…) — HelixDB has no upsert op."""
  def find_or_add_edge_entries(batch: "WriteBatch", var: str, src_var: str, dst_var: str, rel: str, props: Mapping[str, Any]) -> "WriteBatch":
      """Dedupe (src, dst, rel) before add_e — HelixDB is a multigraph."""
  def text_search(label: str, prop: str, query: str, limit: int, projection: Sequence[str]) -> "Traversal":
      """text_search_nodes + value_map([... , "$score"]); limit clamped to 800."""
  def vector_search(label: str, prop: str, vector: Sequence[float], limit: int, projection: Sequence[str]) -> "Traversal":
      """vector_search_nodes + value_map([... , "$distance"])."""
  def cas_page_entries(batch: "WriteBatch", page_props: Mapping[str, Any], expected_hash: str | None) -> "WriteBatch":
      """compare_and_swap semantics via BatchCondition on content_hash (insert-only when expected is None)."""
  ```
- **Extras / tooling edits** (exact):
  - `packages/ai-parrot/pyproject.toml` after `graphindex-postgres = [...]` (`:287`): `helixdb = ["helix-db==0.3.4"]`, `helixdb-embedded = ["ai-parrot[helixdb]", "helix-db-embedded==0.3.3"]`.
  - root `pyproject.toml` `[dependency-groups] dev` (`:61`): add `"helix-db==0.3.4"`, `"helix-db-embedded==0.3.3"` (CI runs `uv sync --all-packages`, `.github/workflows/ci.yml:27`, so no workflow edit).
  - `ruff.toml` per-file-ignores after `:163`: `"packages/ai-parrot/src/parrot/knowledge/helix/client.py" = ["TID251"]`.

### Module 2: docker/helixdb, Makefile, docs, two-writer spike

- **Path**: `docker/helixdb/{Dockerfile,docker-compose.yml,README.md}` (new); `Makefile` (`:920`, `:1097`); `docs/wiki/cheatsheet.md` (`:43`); `docs/wiki/helixdb.md` (new); `sdd/state/FEAT-670/spike-embedded-two-writers.md` (new)
- **Responsibility**: the local/shared server stack and operator docs; the embedded two-writer spike (resolved Q4, wording only).
- **Depends on**: none (M1 for the smoke test only)
- **Interface Skeleton** (file contracts):
  ```yaml
  # docker/helixdb/docker-compose.yml (new)
  services:
    helixdb:
      image: ghcr.io/helixdb/helixdb:${HELIXDB_IMAGE_TAG:-v0.0.12}
      container_name: parrot-helixdb
      ports: ["${HELIXDB_PORT:-6969}:8080"]
      environment: { HELIX_DATA_DIR: /var/lib/helix }
      volumes: ["helixdb-data:/var/lib/helix"]
      healthcheck: { test: ["CMD-SHELL", "wget -q --spider http://127.0.0.1:8080/readyz || exit 1"], interval: 5s, timeout: 3s, retries: 20, start_period: 10s }
  volumes: { helixdb-data: { name: parrot-helixdb-data } }
  ```
  ```make
  # Makefile (modifies Makefile:920 — inserted before `docker-dev:`)
  docker-helixdb:           ## Start the local HelixDB server (docker/helixdb, persistent volume)
  	@docker compose -f docker/helixdb/docker-compose.yml up -d
  # Makefile:1097 — help line added next to docker-whatsapp-bridge
  ```
  README sections (fixed): Start · Env vars (`HELIXDB_URL`, `HELIXDB_API_KEY`, `HELIXDB_IMAGE_TAG`, `HELIXDB_PORT`) · Persistence · **Upgrading (one-way index storage version; backup first)** with the `docker run --rm -v parrot-helixdb-data:/data -v "$PWD":/backup alpine tar czf /backup/helixdb-<date>.tgz -C /data .` command · Troubleshooting (`/healthz`, `/readyz`, uid 65532 on bind mounts).
  Spike output: `sdd/state/FEAT-670/spike-embedded-two-writers.md` with the exact exception class/message observed when two processes open the same `Disk` writer; feeds the guard message in M3 and the docs.

### Module 3: `HelixWikiStore` + `SourceCollectionManager` backend

- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py` (new); `wiki/store.py` (`:2730-2741`, docstring `:561`); `wiki/sources.py` (`:148`, `:184`, new `_helix_*` branch)
- **Responsibility**: full `BaseWikiStore` parity on HelixDB; `Source` manifest entries on the same database.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/wiki/helix_store.py (new)
  WIKI_PLANE = PlaneSchema(plane="wiki", schema_version=SCHEMA_VERSION, labels=[...Page, Symbol, Source, Meta, PageAttr...],
                           edge_labels=["*"])   # SCHEMA_VERSION verified: wiki/store.py:51

  class HelixWikiStore(BaseWikiStore):   # BaseWikiStore verified: wiki/store.py:553
      """HelixDB retrieval plane for one wiki (server or embedded)."""
      supports_attrs: bool = True
      def __init__(self, settings: HelixSettings, wiki_name: str = "", *, read_only: bool = False,
                   body_max_chars: int = 16_000) -> None: ...
      async def initialize(self) -> None:
          """open_helix_client + ensure_plane(WIKI_PLANE); idempotent; called lazily by every public method."""
      async def close(self) -> None: ...
      @property
      def read_only(self) -> bool: ...
      # BaseWikiStore abstract surface — every method one batch (verified: wiki/store.py:600-700):
      async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...
      async def add_edges(self, edges: list[tuple]) -> int: ...
      async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord], edges: Optional[list[tuple[str, str, str]]] = None) -> dict[str, Any]: ...
      async def delete_page(self, concept_id: str) -> bool: ...
      async def upsert_embedding(self, concept_id: str, vector: list[float], model: str = "") -> None:
          """ensure_vector_index(label="Page", prefix="embedding", dimension=len(vector)) then set_property."""
      async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]: ...
      async def list_pages(self, category: Optional[str] = None, limit: int = 100, origin: Optional[list[str]] = None) -> list[dict[str, Any]]: ...
      async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]:
          """text_search on Page.search_text; limit clamped to 800. Contract parity with SQLite (verified: wiki/store.py:2328-2362):
          `category=None` EXCLUDES the "archive" category; an explicit category filters to it; rows carry the same keys."""
      async def search_vector(self, embedding: list[float], limit: int = 10) -> list[dict[str, Any]]:
          """Picks embedding_<len(embedding)>; `score = 1 - $distance` in [-1, 1] (cosine, same scale as
          wiki/store.py:2381 and postgres_store.py:700-714); zero vector or no matching dimension → [] + warning."""
      async def neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both") -> list[dict[str, Any]]: ...
      async def dump_pages(self) -> list[dict[str, Any]]: ...
      async def dump_edges(self) -> list[dict[str, Any]]: ...
      async def stats(self) -> dict[str, Any]: ...
      async def orphan_sources(self) -> list[str]: ...
      async def broken_edges(self) -> list[dict[str, Any]]: ...
      async def missing_bodies(self) -> list[str]: ...
      async def rebuild_index(self) -> dict[str, Any]:
          """Re-issue ensure_plane + every known vector index; returns {"rebuilt": [...]}."""
      async def index_drift(self) -> dict[str, int]: ...
      # concrete-with-default surface overridden (verified: wiki/store.py:680-930):
      async def compare_and_swap_page(self, page: WikiPageRecord, expected_content_hash: Optional[str]) -> bool: ...
      async def get_meta(self, key: str) -> Optional[str]: ...
      async def set_meta(self, key: str, value: str) -> None: ...
      async def get_attrs(self, concept_id: str) -> dict[str, str]: ...
      async def list_by_attrs(self, filters, *, date_key=None, since=None, until=None, limit=200) -> list[dict[str, Any]]: ...
      async def upsert_attrs(self, concept_id: str, attrs: Mapping[str, str], *, replace: bool = True) -> int: ...
      async def upsert_symbols(self, ...) -> int: ...          # same signature as SQLiteWikiStore.upsert_symbols (wiki/store.py:~814)
      async def symbols_for(self, rel_path: str) -> list[SymbolRecord]: ...
      async def find_symbols(self, ...) -> list[SymbolRecord]: ...
      async def search_symbols_fts(self, query: str, limit: int = 20) -> list[SymbolRecord]: ...
      async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]: ...

  # wiki/store.py (modifies :2730 — new branch before `if backend in _EXTRA_BACKENDS:` at :2741)
  #   if backend == "helixdb":  (lazy import of helix_store; kwargs: helix_settings | database, credentials_env, mode, read_only)

  # wiki/sources.py (modifies :148 and :184)
  #   backend: Literal["sqlite", "json", "arangodb", "helixdb"]; helix branch stores SourceManifestEntry as `Source` nodes,
  #   reusing `_run_async` (verified: wiki/sources.py:1224) exactly like `_arango_*` (verified: :1289-1395)
  ```

### Module 4: Configuration and CLI selection surface (exclusive)

- **Path**: `wiki/models.py` (`:114`), `wiki/project.py` (`:186-230`, `:605`, `:616-627`, new `resolve_helix_params` after `:851`), `wiki/cli.py` (`:670`, `:1520`, backend resolution around `:614-626`), `wiki/entity_cli.py` (help strings `:207,258,374,454`), `wiki/federation.py` (`:418` dispatch comment)
- **Responsibility**: every place a backend name is validated or chosen accepts `"helixdb"` and exposes the new `helix_*` settings. One task, exclusive (three Literals + two Choice lists + one resolver).
- **Depends on**: M1 (settings model), M3 (store class)
- **Interface Skeleton**:
  ```python
  # wiki/models.py (modifies :114)
  storage_backend: Literal["sqlite", "memory", "arangodb", "helixdb"] = Field(default="sqlite", ...)

  # wiki/project.py (modifies :605; adds after :627)
  backend: Literal["sqlite", "memory", "arangodb", "helixdb"] = Field(default="sqlite")
  helix_database: str | None = Field(default=None, description="HelixDB database (default wiki_<wiki_name>)")
  helix_credentials_env: str = Field(default="HELIXDB", description="Env prefix → HELIXDB_URL / HELIXDB_API_KEY / HELIXDB_MODE")
  helix_mode: Literal["server", "embedded"] = Field(default="server")

  def resolve_helix_params(config: WikiProjectConfig, *, root: Path | None = None) -> HelixSettings:
      """Mirror of resolve_arango_params (verified: wiki/project.py:851) for the helixdb backend."""

  SERVER_BACKENDS: frozenset[str] = frozenset({"arangodb", "helixdb"})   # design-research S1/S8: one capability set, not per-site string checks
  class WikiProjectConfig:
      @property
      def is_server_backend(self) -> bool: ...
      def is_built(self, root: Path) -> bool:
          """(modifies :774-788) helixdb+server → True (deferred to initialize(), like arangodb);
          helixdb+embedded → (storage_dir/'helix'/<database>).exists(); never the `pages/` fallthrough."""

  # wiki/project.py WikiNamespaceConfig (modifies :186-230 docstring + the validator at :267 that forces backend="arangodb"
  #   when `database` is set): only force arangodb when backend is unset; "helixdb" + database is a built-in server backend.
  # wiki/federation.py open_namespace_store (modifies :396-430): pass `arango_params` ONLY to arangodb; pass `helix_settings`
  #   (resolve_helix_params(_helix_config_for(cfg))) to helixdb; never hand arango kwargs to another backend.
  # wiki/cli.py (modifies :670 and :1520): click.Choice(["sqlite", "memory", "arangodb", "helixdb"])
  # wiki/cli.py backend resolution (:614-626): `--backend helixdb` resolves via resolve_helix_params, same precedence as arangodb
  # Audit (S1): every `== "arangodb"` site in wiki/cli.py (15), wiki/toolkit.py (3), wiki/sync.py (4), wiki/federation.py (4),
  #   wiki/sources.py (20) is reviewed; sites that mean "server-hosted backend" switch to SERVER_BACKENDS / is_server_backend,
  #   sites that mean "needs ArangoDB params" stay literal. The task lists each site with its classification.
  ```

### Module 5: Ledger hard cut — `LedgerTxn` + `HelixLedgerStore`

- **Path**: `wiki/ledger/store.py` (`:54-116`), `wiki/ledger/helix_store.py` (new), `wiki/ledger/index.py` (`:128,157,167,189,200,210,245,254-259,276,359,375-377,440,477,511,548-549`), `wiki/ledger/sdd_ingest.py` (`:99-102,195-198`), `wiki/ledger/service.py` (`:140,164`)
- **Responsibility**: `ledger_transaction()` yields a backend-neutral `LedgerTxn` (resolved Q5, hard cut, no shim); SQLite wraps the connection, HelixDB collects one write batch committed at context exit; `LedgerService` dispatches on `WikiProjectConfig.backend`.
- **Depends on**: M1, M3, M4
- **Interface Skeleton**:
  ```python
  # wiki/ledger/store.py (modifies :54 — signature change; adds the protocol)
  class LedgerTxn(Protocol):
      """Backend-neutral composable ledger write. Derived from the 9 call sites' actual use
      (verified: ledger/index.py:128,157,167,189,200,210,245,254-259,375-377,549; sdd_ingest.py:100-102,196-198)."""
      async def upsert_pages(self, pages: list[WikiPageRecord]) -> None: ...
      async def add_edges(self, edges: list[tuple]) -> None: ...
      async def get_page_body(self, concept_id: str) -> str | None: ...
      async def set_state(self, key: str, value: str) -> None: ...
      async def clear_all(self) -> None:
          """DELETE pages/edges/ledger_state (rebuild path, index.py:375-377)."""
      async def list_pages(self, category: str) -> list[tuple[str, str, str]]:
          """(concept_id, body, updated_at) — compact path, index.py:549."""

  class LedgerReader(Protocol):
      """Read-only counterpart (design-research S2): replaces LedgerService's direct `store._read()` SQL
      (verified: ledger/service.py:178,309,467)."""
      async def get_page_body(self, concept_id: str) -> str | None: ...
      async def list_pages(self, category: str) -> list[tuple[str, str, str]]: ...
      async def get_state(self, key: str) -> str | None: ...

  class LedgerStore(SQLiteWikiStore):   # verified: ledger/store.py:24
      @asynccontextmanager
      async def ledger_transaction(self, operation: str) -> AsyncIterator[LedgerTxn]:
          """SQLite implementation: yields _SQLiteLedgerTxn(conn) inside FEAT-557's _write(operation)."""
      @asynccontextmanager
      async def ledger_read(self) -> AsyncIterator[LedgerReader]:
          """SQLite: wraps _read(); HelixDB: a read-batch reader."""
      # upsert_pages_in / add_edges_in (verified :107/:116) remain as the SQLite txn's internals
  # ledger/index.py: `LedgerIndex.apply_event(event, conn: aiosqlite.Connection)` (:103), `_read_issue(conn, …)` (:126) and the
  #   helper at :136 are retyped to `LedgerTxn`; no `aiosqlite` import remains in index.py / sdd_ingest.py / service.py.

  # wiki/ledger/helix_store.py (new)
  class HelixLedgerStore(HelixWikiStore):
      """Ledger plane on HelixDB: ledger_state → Meta nodes `ledger_state:<key>`."""
      async def ledger_transaction(self, operation: str) -> AsyncIterator[LedgerTxn]:
          """Yields _HelixLedgerTxn that accumulates one write_batch; commits on exit; rollback = discard."""
      async def read_cursor(self) -> tuple[int, str | None]: ...   # same contract as ledger/store.py:75

  # wiki/ledger/service.py (modifies :140 and :164): `backend == "helixdb"` → HelixLedgerStore(resolve_helix_params(config, root=…).with_database(f"ledger_{wiki_name}"))
  # wiki/ledger/service.py (modifies :178, :309, :467): `async with self.store._read() as conn:` → `async with self.store.ledger_read() as reader:`
  ```
- **Migration note** (design-research S11, confirmed part): the ledger's canonical source is the append-only event log
  (`ledger/log.py`); switching backend requires `wikitoolkit ledger rebuild` (the existing `ledger.rebuild` replay at `index.py:359`),
  documented in `docs/wiki/helixdb.md`. Whether a cross-backend *copy* command is also needed is §8 Q2.

### Module 6: `HelixSchemaStore` (SQL schema overlay plane)

- **Path**: `wiki/schema/helix_store.py` (new); `wiki/schema/service.py` (`:66`, `:82`)
- **Responsibility**: schema-plane parity: `columns` table → `Column` nodes keyed `(table_id, name)` with `COLUMN_OF` edges to the table page.
- **Depends on**: M1, M3, M4
- **Interface Skeleton**:
  ```python
  # wiki/schema/helix_store.py (new)
  class HelixSchemaStore(HelixWikiStore):
      """Schema overlay plane on HelixDB; same public surface as SchemaStore (verified: schema/store.py:120-226)."""
      async def upsert_columns(self, columns: list[ColumnRecord]) -> int: ...
      async def columns_for(self, table_id: str) -> list[ColumnRecord]: ...
      async def find_columns(self, ...) -> list[ColumnRecord]: ...           # same signature as schema/store.py:135
      async def replace_schema_slice(self, ...) -> dict[str, Any]: ...        # same signature as schema/store.py:195
      async def fold_ddl_table(self, ...) -> ...: ...                        # same signature as schema/store.py:226
  # wiki/schema/service.py (modifies :66 and :82): backend dispatch → HelixSchemaStore(database=f"schema_{wiki_name}")
  ```

### Module 7: `HelixPersistence` (GraphIndex) + persistence resolver

- **Path**: `graphindex/persist_helix.py` (new); `graphindex/persistence_resolver.py` (new); `graphindex/factory.py` (`:197-261`); `graphindex/loader.py` (`:151-190` ctor, `:288-293`); `wiki/runtime.py` (`:91`); `wiki/cli.py` (`:4011`, `:4108`, `:4561`, `:4623`); `flows/dev_loop/graph_memory.py` (`:142`)
- **Responsibility**: the GraphIndex plane on HelixDB with the full commit protocol; one resolver so the five direct `SQLitePersistence(...)` sites choose by config.
- **Depends on**: M1, M4 (config fields)
- **Interface Skeleton**:
  ```python
  # graphindex/persist_helix.py (new) — mirrors SQLitePersistence (verified: graphindex/persist_sqlite.py:138-856)
  GRAPHINDEX_PLANE = PlaneSchema(plane="graphindex", schema_version="1", labels=[GNode(unique node_id, eq kind/source_uri/parent_id, text search_text),
                                 GFile(unique source_uri), GCommit(unique commit_id, eq run_id/agent_id, range seq), GCommitItem(eq item_type/item_key)], edge_labels=["*"])
  class HelixPersistence:
      """GraphIndex persistence on HelixDB; one database per tenant (resolved Q7)."""
      def __init__(self, settings_factory: Callable[[TenantContext], HelixSettings]) -> None: ...
      async def close(self) -> None: ...
      async def persist_graph(self, ctx: TenantContext, nodes: list[UniversalNode], edges: list[UniversalEdge]) -> dict[str, Any]: ...
      async def replace_document_slice(self, ctx: TenantContext, document_uri: str, nodes: list[UniversalNode], edges: list[UniversalEdge]) -> dict[str, Any]:
          """ONE write batch: drop GNode/edges with source_uri == document_uri, then add."""
      async def is_stale(self, ctx: TenantContext, source_uri: str, mtime: float, sha1: str) -> bool: ...
      async def load_graph(self, ctx: TenantContext) -> tuple[list[UniversalNode], list[UniversalEdge]]: ...
      async def apply_update(self, ctx: TenantContext, update: GraphUpdate) -> CommitReceipt:
          """Graph change + GCommit + GCommitItems in ONE atomic batch (design-research S5):
          - edge identity: every edge carries `edge_key = f"{source_id}|{target_id}|{kind}"` (equality index; HelixDB has no
            unique EDGE index) and find-or-add runs inside the same batch, so one request never duplicates;
          - commit sequence: `seq` is read-increment-written on the Meta node `gi_commit_seq` inside the same batch
            (HelixDB serialises write transactions, so the allocation is atomic per tenant database);
          - pre-images: GCommitItem records node pre-images AND the incident edges dropped with a removed node,
            so revert can restore them."""
      async def get_commit(self, ctx: TenantContext, commit_id: str) -> Optional[dict[str, Any]]: ...
      async def list_commits(self, ctx: TenantContext, *, run_id: str | None = None, agent_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]: ...
      async def revert_commit(self, ctx: TenantContext, commit_id: str) -> dict[str, Any]:
          """Replay items in reverse order inside ONE batch; conflict rule = persist_sqlite.py:856-908 with `seq` in place of
          rowid: a later commit (higher seq) touching any of this commit's item keys ⇒ revert refused."""

  # graphindex/persistence_resolver.py (new)
  def graphindex_persistence_for(config: WikiProjectConfig, root: Path) -> Any:
      """config.backend == "helixdb" → HelixPersistence(…gi_<tenant>…) else SQLitePersistence(config.graph_path(root))  # graph_path verified: wiki/project.py:721"""

  # graphindex/factory.py (modifies :253 `elif backend == "postgres":` — adds `elif backend == "helixdb":` + kwargs helix_settings: HelixSettings | None)
  # graphindex/loader.py (modifies ctor :151 + :290 — design-research S4: explicit, mutually exclusive selection):
  #   new kwargs `backend: Literal["sqlite", "arangodb", "helixdb"] | None = None`, `helix_settings: Optional[HelixSettings] = None`.
  #   Precedence: explicit `backend` wins; legacy `sqlite_dir` alone ⇒ "sqlite"; `arango_params` alone ⇒ "arangodb";
  #   conflicting legacy arguments (e.g. sqlite_dir + backend="helixdb", or sqlite_dir + arango_params) raise ValueError at
  #   construction — never a silent pick. `build_graph_memory_toolkit` applies the same rule (db_dir ⇒ sqlite unless backend given).
  # wiki/runtime.py:91, wiki/cli.py:4011/4108/4561/4623, flows/dev_loop/graph_memory.py:142 → graphindex_persistence_for(...)
  ```

### Module 8: Ontology typed traversals + `HelixOntologyGraphStore`

- **Path**: `ontology/graph_store.py` (`:53-271+`); `ontology/helix_graph_store.py` (new); `ontology/factory.py` (new); `ontology/authorization.py` (`:257`, `:339`); `ontology/entity_resolver.py` (`:384`, `:427`); `ontology/mixin.py` (`:337`, `:359`, `:379`); `graphindex/loader.py` (`:313`); `packages/ai-parrot-tools/src/parrot_tools/graphindex/flowtask.py` (`:220`); `parrot_tools/legal/wiki_store.py`; `parrot_tools/legal/boe/sync.py`
- **Responsibility**: remove raw AQL from callers behind typed traversal methods (resolved Q3), implement them on ArangoDB (AQL inside) and HelixDB (DSL), and give callers a factory.
- **Scope caveat (design-research S3, escalated as §8 Q1)**: the eight call sites do not only run fixed queries — `mixin.py:337/359/379` execute `ResolvedIntent.aql` (`ontology/intent.py:42,150,212,220`), which is the ontology YAML's `TraversalPattern.query_template` (`ontology/schema.py:261-288`): arbitrary AQL with bind variables declared per ontology. Named methods cannot absorb an open-ended template. Until Q1 is answered, M8's contract is: typed methods cover the fixed queries (`authorization.py:257/339`, `entity_resolver.py:384/427`); template-driven intents keep a scoped `execute_pattern(ctx, pattern, binds)` that ArangoDB implements with AQL and `HelixOntologyGraphStore` implements **only** for patterns that also declare a `traversal_spec`, raising `UnsupportedTraversal` otherwise. The decision between "validated `TraversalSpec` in ontology YAML" and "template patterns stay Arango-only" is the user's (Q1).
- **Depends on**: M1, M7 (shared `GNode`-style helpers), M4
- **Interface Skeleton**:
  ```python
  # ontology/graph_store.py (modifies — adds to OntologyGraphStore, verified: ontology/graph_store.py:53)
  class OntologyGraphStore:
      async def _execute_aql(self, ctx: TenantContext, aql: str, bind_vars=None, collection_binds=None) -> list[dict[str, Any]]:
          """Renamed from execute_traversal (verified :271); private, ArangoDB-only."""
      # typed surface — exact semantics derived task-time from the AQL at the 8 call sites:
      async def neighbours(self, ctx: TenantContext, *, start_key: str, start_collection: str, edge_collections: Sequence[str],
                           direction: Literal["out", "in", "any"] = "any", min_depth: int = 1, max_depth: int = 1,
                           vertex_filter: Mapping[str, Any] | None = None, limit: int = 100) -> list[dict[str, Any]]:
          """authorization.py:257/:339 and mixin.py:337/:359/:379 traversals."""
      async def find_entities(self, ctx: TenantContext, *, collection: str, filters: Mapping[str, Any],
                              text: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
          """entity_resolver.py:384/:427 lookups (ArangoSearch view on Arango; BM25 text index on Helix)."""
      async def path_between(self, ctx: TenantContext, *, src_key: str, dst_key: str, edge_collections: Sequence[str], max_depth: int = 4) -> list[dict[str, Any]]: ...
      async def execute_pattern(self, ctx: TenantContext, pattern: TraversalPattern, binds: Mapping[str, Any]) -> list[dict[str, Any]]:
          """Template-driven intents (mixin.py:337/359/379 via ResolvedIntent.aql). ArangoDB: runs pattern.query_template.
          TraversalPattern verified: ontology/schema.py:261 (query_template :288)."""

  class UnsupportedTraversal(NotImplementedError):
      """Raised by HelixOntologyGraphStore.execute_pattern for a pattern without a backend-neutral traversal_spec (pending §8 Q1)."""

  # ontology/helix_graph_store.py (new)
  class HelixOntologyGraphStore:
      """Same public surface as OntologyGraphStore (initialize_tenant :91, upsert_nodes :311, create_edges :411, get_all_nodes :488,
      soft_delete_nodes :517, ensure_collection :570, get_document :598, upsert_document :622, insert_document :650,
      remove_document :669, query_documents :697, get_all_edges :738, edges_incident :764, remove_edge_by_triple :791)
      + the typed surface above; one database per tenant (`ont_<tenant>`)."""
      def __init__(self, settings_factory: Callable[[TenantContext], HelixSettings]) -> None: ...

  # ontology/factory.py (new)
  def ontology_graph_store_for(backend: Literal["arangodb", "helixdb"], **kwargs: Any) -> OntologyGraphStore | HelixOntologyGraphStore: ...
  ```

### Module 9: PageIndex projection

- **Path**: `pageindex/helix_projection.py` (new); `pageindex/toolkit.py` (`:114-133`); `pageindex/hybrid_search.py` (`:73-94` ctor, `:177`, `:199`)
- **Responsibility**: project whole tree **generations** into HelixDB (`TreeNode` + `CHILD_OF`), and let `HybridPageIndexSearch` serve BM25/vector legs from HelixDB when a projection is configured (resolved Round 2c: files stay canonical).
- **Design (design-research S6, confirmed)**: `splice_subtree()` → `reindex_node_ids()` (`pageindex/tree_ops.py:89-141`) renumbers node ids tree-wide before `_save_node_markdown` and `_persist` (`toolkit.py:851-980`, `:237`), so an incremental projection keyed by `node_id` would serve stale or mis-attached bodies. The projection is therefore **generation-based**: `_persist()` is the single trigger, every projection replaces the tree's whole node set in one atomic batch stamped with a `generation` (monotonic int stored on Meta `pageindex_gen:<tree>`), and search requests pass the generation they expect; a mismatch (projection failed or lagging) makes `HybridPageIndexSearch` fall back to the `bm25s`/numpy path for that call and log once.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # pageindex/helix_projection.py (new)
  class PageIndexHelixProjection:
      """Generation-based projection of one PageIndex tree: TreeNode(unique key f"{tree_name}:{node_id}", generation, text search_text,
      embedding_<d>) + CHILD_OF edges, replaced wholesale per generation."""
      def __init__(self, settings: HelixSettings) -> None: ...
      async def project_generation(self, tree_name: str, generation: int, tree: dict[str, Any],
                                   body_loader: Callable[[str], Optional[str]], matrix: "np.ndarray | None" = None,
                                   node_order: Sequence[str] | None = None) -> dict[str, int]:
          """ONE write batch: drop every TreeNode of `tree_name`, add the new nodes/edges/embeddings, set Meta pageindex_gen."""
      async def current_generation(self, tree_name: str) -> int | None: ...
      async def drop_tree(self, tree_name: str) -> int: ...
      async def bm25_rank(self, tree_name: str, generation: int, query: str, top_k: int) -> list[str] | None:
          """None when the stored generation != `generation` (caller falls back)."""
      async def vector_rank(self, tree_name: str, generation: int, query_vector: Sequence[float], top_k: int) -> list[str] | None: ...

  # pageindex/toolkit.py (modifies :237 `_persist` — bumps the in-memory generation and schedules project_generation; :114-133 — new kwarg
  #   `helix_settings: HelixSettings | None = None` builds the projection and hands it to HybridPageIndexSearch)
  # pageindex/hybrid_search.py (modifies ctor :73 — new kwarg `helix_projection: PageIndexHelixProjection | None = None`;
  #   _bm25_rank :177 and _vec_rank :199 delegate when the projection is set and the generation matches; mark_dirty :119 unchanged)
  ```

### Module 10: BookStore projection

- **Path**: `bookstore/helix_projection.py` (new); `bookstore/library.py` (`:230` catalog construction, `:351` `search_book`, `:411` `search`, plus the async mutation paths that call `CatalogStore.upsert/remove/upsert_relations/upsert_communities`)
- **Responsibility**: mirror cards, relations and communities into HelixDB (`Book`, `RELATES_TO`, `BookCommunity`/`MEMBER_OF`) and serve BM25 search from it when projected.
- **Design (design-research S7, confirmed)**: `CatalogStore` is deliberately synchronous (short-lived `sqlite3` connections, `catalog.py:9-19,183-195`) and `Library` is the async boundary (`library.py:411` awaits then calls the sync catalog). The projection therefore lives **in `Library`**, not in `CatalogStore`: `Library` owns one `BookstoreHelixProjection` per scope, calls it `await`-side after each successful canonical catalog write, and `Library.search()` consults it before the sync FTS. `CatalogStore` is **not modified**. Failure policy: the canonical SQLite commit always wins; a projection write failure is logged and sets `projection_stale[scope] = True`, after which `Library.search()` uses the SQLite FTS path until `reproject(scope)` succeeds.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # bookstore/helix_projection.py (new)
  class BookstoreHelixProjection:
      def __init__(self, settings: HelixSettings) -> None: ...
      async def upsert_card(self, card: BookCard) -> None: ...
      async def remove_card(self, book_id: str) -> None: ...
      async def upsert_relations(self, relations: list[BookRelation]) -> None: ...
      async def upsert_communities(self, communities: list[BookCommunity]) -> None: ...
      async def reproject(self, cards: list[BookCard], relations: list[BookRelation], communities: list[BookCommunity]) -> dict[str, int]:
          """Full rebuild from the canonical catalog in one batch (used after a failure or on first enable)."""
      async def search(self, query: str, top_k: int = 8) -> list[tuple[str, float]]:
          """(book_id, $score) via text_search on Book.search_text."""
  # bookstore/library.py (modifies :230 — build the projection per scope when helix settings resolve and the library config enables it;
  #   :411 `search` and :351 `search_book` consult the projection first; every mutation path mirrors after the sync catalog call)
  ```

### Module 11: Parity and live test suites, documentation

- **Path**: `packages/ai-parrot/tests/knowledge/helix/` (new: `conftest.py`, `test_client_settings.py`, `test_bootstrap.py`, `test_dsl.py`), `tests/knowledge/wiki/test_helix_store.py`, `test_helix_store_cas.py`, `test_helix_symbols.py`, `test_helix_sources.py`, `tests/knowledge/wiki/ledger/test_helix_ledger.py`, `tests/knowledge/wiki/schema/test_helix_schema_store.py`, `tests/knowledge/graphindex/test_persist_helix.py`, `test_commit_protocol_helix.py`, `tests/knowledge/ontology/test_helix_graph_store.py`, `test_typed_traversals.py`, `tests/knowledge/pageindex/test_helix_projection.py`, `tests/knowledge/bookstore/test_helix_projection.py`, `tests/knowledge/helix/test_live_server.py`; `docs/wiki/helixdb.md`, `docs/wiki/cheatsheet.md`
- **Responsibility**: a **backend contract matrix** (design-research S9, confirmed): the behavioural suites are parametrised over `sqlite`, `helix-memory` and `helix-live` fixtures rather than copied per backend, and cover read-only writes, CAS races, source-slice replacement, attrs/symbols/meta/lint methods, tenant isolation, close/reopen, and failure during index bootstrap. Embedded `InMemory` runs in CI (resolved Q6); live-server tests gated on `HELIXDB_URL` reachability with the ArangoDB `skipif` shape (`tests/knowledge/wiki/test_arango_store_cas.py:17-44`). Plus a **compatibility gate** (design-research S10, confirmed): the SDK version, the embedded wheel and the pinned image are verified together before any backend logic test is trusted.
- **Depends on**: M1–M10
- **Interface Skeleton**:
  ```python
  # tests/knowledge/helix/conftest.py (new)
  @pytest.fixture
  async def helix_memory_settings() -> HelixSettings:
      """mode=MEMORY, database=f"test_{uuid4().hex}"; skips with reason when `helixdb_uniffi` is not importable."""
  @pytest.fixture
  async def helix_live_settings() -> HelixSettings:
      """pytest.mark.live; skipif HELIXDB_URL unreachable (socket probe like test_arango_store_cas.py:33-44)."""
  @pytest.fixture(params=["sqlite", "helix-memory", pytest.param("helix-live", marks=pytest.mark.live)])
  async def wiki_store_matrix(request, tmp_path, helix_memory_settings, helix_live_settings) -> BaseWikiStore:
      """Contract-matrix fixture: the same behavioural test body runs against every backend."""
  # tests/knowledge/helix/test_compat_gate.py (new)
  #   test_native_wheel_imports (unit) — `import helixdb_uniffi` + HelixDb.open(IN_MEMORY) round-trip
  #   test_sdk_speaks_to_pinned_image (live) — a DSL read_batch from helix-db==0.3.4 is accepted by ghcr.io/helixdb/helixdb:${HELIXDB_IMAGE_TAG}
  #   test_async_only_usage (unit) — AST scan: no `helixdb.Client(` / `Client.embedded(` outside tests; `httpx` imported only via helix/client.py
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_resolve_helix_settings_env_chain` | M1 | `HELIXDB_URL` / `HELIXDB_API_KEY` / `HELIXDB_MODE` via os.environ → navconfig → defaults; embedded requires `storage_dir` |
| `test_open_helix_client_probe_fails_fast` | M1 | aiohttp `/readyz` probe retries then `HelixUnavailable`; no `helixdb` import when the extra is missing → `HelixExtraMissing` names `ai-parrot[helixdb]` |
| `test_ensure_plane_idempotent_and_polls_receipts` | M1 | second call creates nothing; blocked build → `HelixUnavailable` with blocker code |
| `test_ensure_vector_index_lazy_per_dimension` | M1 | dims 3 then 5 → two properties, `Meta vector_dims:Page == [3,5]` |
| `test_dsl_find_or_add_edge_dedupes` | M1 | same `(src,dst,rel)` twice → one edge |
| `test_dsl_cas_entries_conditions` | M1 | insert-only when expected is None; hash mismatch → no write |
| `test_helix_store_parity_pages_edges_fts` | M3 | the `SQLiteWikiStore` behavioural cases (upsert/replace slice/delete/neighbors/dump/stats/lint) on `HelixWikiStore` |
| `test_helix_store_cas` | M3 | clone of `tests/knowledge/wiki/test_store_cas.py` cases |
| `test_helix_store_attrs` / `test_helix_symbols` | M3 | clones of `test_store_attrs.py` / `test_postgres_symbols.py` cases |
| `test_helix_sources_manager` | M3 | `SourceCollectionManager(backend="helixdb")` add/list/stale/mark_ingested |
| `test_create_wiki_store_helixdb_dispatch` | M3/M4 | `create_wiki_store(backend="helixdb")` returns `HelixWikiStore`; unknown still raises |
| `test_config_literals_accept_helixdb` | M4 | `WikiConfig`, `WikiProjectConfig`, `WikiNamespaceConfig`, CLI `click.Choice` |
| `test_ledger_txn_sqlite_and_helix_parity` | M5 | ingest → claim → close → compact on both stores through `LedgerTxn` |
| `test_ledger_transaction_yields_txn_not_connection` | M5 | hard cut: yielded object has no `.execute` |
| `test_helix_schema_store_columns` | M6 | `upsert_columns` / `columns_for` / `find_columns` / `replace_schema_slice` parity |
| `test_persist_helix_parity` | M7 | clone of `test_persist_sqlite.py` cases |
| `test_commit_protocol_helix` | M7 | clone of `test_persist_commit_protocol.py` (apply/get/list/revert, conflict detection) |
| `test_graphindex_persistence_resolver` | M7 | sqlite vs helixdb by config; the five call sites use the resolver |
| `test_typed_traversals_replace_aql` | M8 | no `execute_traversal(` string remains outside `graph_store.py`; `FakeGraphStore` implements the typed surface |
| `test_helix_ontology_store_surface` | M8 | every `OntologyGraphStore` public method exists on `HelixOntologyGraphStore` and behaves on InMemory |
| `test_pageindex_projection_ranks` | M9 | `bm25_rank` / `vector_rank` order vs the `bm25s`/numpy baseline on a fixture tree (top-k set equality) |
| `test_hybrid_search_delegates_when_projected` | M9 | `_bm25_rank` / `_vec_rank` call the projection; without it the legacy path runs |
| `test_bookstore_projection_search` | M10 | `Library`-owned projection: card upsert → BM25 search; relations → edges; communities → membership; projection failure ⇒ `projection_stale` + SQLite fallback; `reproject` clears it |
| `test_pageindex_generation_fallback` | M9 | generation mismatch ⇒ `bm25_rank` returns `None` and `HybridPageIndexSearch` uses the legacy leg; a splice + `_persist` re-projects the whole tree |
| `test_extras_and_ruff_exemption` | M1 | `helixdb` / `helixdb-embedded` extras present; only `knowledge/helix/client.py` imports `httpx`-dependent `helixdb.async_client` |
| `test_search_fts_archive_default_and_score_scale` | M3 | `category=None` excludes `archive`; explicit category filters; `search_vector` score ∈ [-1,1] = `1 - $distance`; zero vector ⇒ `[]` |
| `test_loader_backend_precedence` | M7 | explicit `backend` wins; `sqlite_dir` alone ⇒ sqlite; conflicting legacy args ⇒ `ValueError` |
| `test_commit_seq_and_edge_key_atomic` | M7 | concurrent `apply_update` via two clients ⇒ distinct `seq`, no duplicate `edge_key`; node removal records incident edges; revert restores them |
| `test_ledger_reader_protocol` | M5 | `LedgerService` reads go through `ledger_read()`; no `_read()` / `aiosqlite` in `ledger/service.py`, `index.py`, `sdd_ingest.py` |
| `test_is_built_and_server_backends` | M4 | `is_built()` for helixdb server/embedded; `SERVER_BACKENDS` sites in cli/toolkit/sync/federation/sources classified; namespace `database` + `backend: helixdb` is not coerced to arangodb |
| `test_execute_pattern_unsupported` | M8 | `HelixOntologyGraphStore.execute_pattern` raises `UnsupportedTraversal` for a template-only pattern; ArangoDB store runs it |
| `wiki_store_matrix` parametrised suites | M11 | CAS, attrs, symbols, replace-slice, read-only writes, close/reopen, bootstrap failure on `sqlite` / `helix-memory` / `helix-live` |
| `test_native_wheel_imports` / `test_async_only_usage` | M11 | compatibility gate (S10) |

### Integration Tests
| Test | Description |
|---|---|
| `test_live_server_wiki_roundtrip` (`live`) | against `docker/helixdb`: build a small wiki, FTS + vector + neighbours, `wikitoolkit lint` clean |
| `test_live_server_concurrent_writers` (`live`) | two processes `upsert` concurrently through the server; no lost writes |
| `test_live_graphindex_commit_revert` (`live`) | `GraphPublisher` apply → revert on the server |
| `test_compose_readyz` (`live`) | `docker compose up` → `/readyz` 200 within `start_period` |
| `test_sdk_speaks_to_pinned_image` (`live`) | compatibility gate: `helix-db==0.3.4` DSL request accepted by `ghcr.io/helixdb/helixdb:${HELIXDB_IMAGE_TAG}` (S10) |
| `test_rebuild_from_canonical_sources` (`live`) | `wikitoolkit build --backend helixdb` then `wikitoolkit lint` + `stats` counts equal the SQLite plane built from the same tree (S11 confirmed part) |

### Test Data / Fixtures
```python
# tests/knowledge/helix/conftest.py
helixdb_uniffi = pytest.importorskip("helixdb_uniffi", reason="helix-db-embedded not installed (ai-parrot[helixdb-embedded])")

@pytest.fixture
async def helix_store(helix_memory_settings) -> HelixWikiStore:
    store = HelixWikiStore(helix_memory_settings, wiki_name="t")
    await store.initialize()
    yield store
    await store.close()

@pytest.fixture
def helix_live_settings():
    url = os.getenv("HELIXDB_URL")
    if not url or not _reachable(url):            # same shape as test_arango_store_cas.py:33-44
        pytest.skip("HelixDB live fixture unavailable: set HELIXDB_URL")
    return resolve_helix_settings(database=f"test_{uuid.uuid4().hex}")
```

---

## 5. Acceptance Criteria

- [ ] **AC1** `create_wiki_store(storage_dir, backend="helixdb", …)` returns a `HelixWikiStore`; every `BaseWikiStore` abstract method and the attrs/meta/symbols/CAS surface pass the parity suites on embedded `InMemory` (M3, M11).
- [ ] **AC2** `backend: helixdb` is accepted by `WikiConfig.storage_backend`, `WikiProjectConfig.backend`, `WikiNamespaceConfig`, `wikitoolkit build --backend helixdb`, `WIKI_STORE_BACKEND=helixdb`, and `SourceCollectionManager(backend="helixdb")`; unknown names still raise `ValueError` (M4).
- [ ] **AC3** Selecting `helixdb` without the extra raises an error naming `ai-parrot[helixdb]` (or `[helixdb-embedded]` for embedded mode) — never a silent fallback (M1).
- [ ] **AC4** `HelixPersistence` passes clones of `test_persist_sqlite.py` and `test_persist_commit_protocol.py`; `build_graph_memory_toolkit(backend="helixdb")` and `GraphIndexLoader(helix_settings=…)` work; the five direct `SQLitePersistence(...)` call sites go through `graphindex_persistence_for` (M7).
- [ ] **AC5** `ledger_transaction()` yields a `LedgerTxn` on both stores; `grep -rn "aiosqlite.Connection" packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py sdd_ingest.py` is empty; `wikitoolkit ledger` commands pass on both backends (M5).
- [ ] **AC6** `HelixSchemaStore` passes the schema-plane column tests; `SchemaPlaneService` dispatches by backend (M6).
- [ ] **AC7** No caller outside `ontology/graph_store.py` references `execute_traversal`; the eight former call sites use typed methods; `HelixOntologyGraphStore` exposes every public method of `OntologyGraphStore`; `parrot_tools` callers use `ontology_graph_store_for` (M8).
- [ ] **AC8** With a projection configured, `HybridPageIndexSearch` BM25 and vector legs return the same top-k set as the `bm25s`/numpy path on the fixture tree; without one, behaviour is byte-identical to today (M9).
- [ ] **AC9** `CatalogStore.search()` delegates to HelixDB when projected and is unchanged otherwise; relations and communities are mirrored (M10).
- [ ] **AC10** Vector indexes are created lazily per dimension; a query vector with no matching index returns `[]` with a warning, never an exception (M1/M3).
- [ ] **AC11** `search_fts` clamps `limit` to 800 and `search_text` to `body_max_chars`; a HelixDB admission rejection surfaces as `HelixWriteRejected` naming the key (M3).
- [ ] **AC12** `docker/helixdb/docker-compose.yml` uses `${HELIXDB_IMAGE_TAG:-v0.0.12}`, a named volume at `HELIX_DATA_DIR`, a `/readyz` healthcheck; `make docker-helixdb` exists; there is **no** embedded Makefile target; README has the backup-before-upgrade section (M2).
- [ ] **AC13** `sdd/state/FEAT-670/spike-embedded-two-writers.md` records the observed error class, and `helix_mode=embedded` is refused while `wiki.lock` is held, with a message pointing to server mode (M2/M3).
- [ ] **AC14** Extras `helixdb` and `helixdb-embedded` exist; root `dev` group installs both wheels; `ruff check` passes with `TID251` exempted **only** for `parrot/knowledge/helix/client.py`; no sync `helixdb.Client` is used anywhere (M1).
- [ ] **AC15** CI (`uv sync --all-packages`) runs the embedded unit tier; live tests are `-m live` and skip without `HELIXDB_URL` (M11).
- [ ] **AC16** No file under `wiki/arango_store.py`, `graphindex/persist.py`, `docker/arango/` changes except the typed-traversal additions in `ontology/graph_store.py`; no deprecation warning mentions ArangoDB (Q8).
- [ ] **AC17** `ruff check --fix` and the feature's merge-tier selection pass; docs updated (`docs/wiki/helixdb.md`, cheatsheet).
- [ ] **AC18** `search_fts(category=None)` excludes `archive`; `search_vector` scores are `1 - $distance` in [-1, 1]; zero vectors return `[]` (S12).
- [ ] **AC19** `WikiProjectConfig.is_built()` never falls through to the `pages/` probe for `helixdb`; a namespace with `database` + `backend: helixdb` is not coerced to `arangodb`; `open_namespace_store` never passes `arango_params` to a non-ArangoDB backend (S1, S8).
- [ ] **AC20** `GraphIndexLoader` / `build_graph_memory_toolkit` apply the explicit-backend precedence rule and raise on conflicting legacy arguments (S4).
- [ ] **AC21** `HelixPersistence` edges carry `edge_key`; `seq` is allocated inside the commit batch; node removal records incident edges and `revert_commit` restores them; `test_commit_seq_and_edge_key_atomic` passes on `helix-live` (S5).
- [ ] **AC22** PageIndex projection is generation-based with legacy fallback on mismatch; BookStore projection lives in `Library`, `CatalogStore` is unmodified, projection failure never fails the canonical write (S6, S7).
- [ ] **AC23** `docs/wiki/helixdb.md` documents the migration path per plane: wiki/graphindex = rebuild from canonical sources (`wikitoolkit build --backend helixdb`), ledger = `wikitoolkit ledger rebuild` event-log replay, pageindex/bookstore = `reproject`; `test_rebuild_from_canonical_sources` passes (S11 confirmed part).
- [ ] **AC24** The compatibility gate (`test_native_wheel_imports`, `test_async_only_usage`, live `test_sdk_speaks_to_pinned_image`) exists and is green (S10).

---

## 6. Codebase Contract

> Re-verified 2026-10-14 against dev @ `246f1bb6d` (after the FEAT-540 spec review commit `fe06d4329`; no `parrot/knowledge` file changed between the brainstorm's verification base `0c06b9c6b` and this commit).

### Verified Imports
```python
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, WikiPageRecord, SymbolRecord, register_wiki_backend, create_wiki_store, SCHEMA_VERSION, SQLitePragmaPolicy, WikiStoreBusy, AttrsUnsupportedError  # verified: wiki/store.py:51,263,284,429,433,539,553,948,2665
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiNamespaceConfig, resolve_arango_params, sqlite_policy_from_config, wiki_write_lock, _env_credential  # verified: wiki/project.py:561,186,851,928,76,822
from parrot.knowledge.wiki.models import WikiConfig  # storage_backend Literal verified: wiki/models.py:114
from parrot.knowledge.wiki.sources import SourceCollectionManager  # verified: wiki/sources.py:144-148
from parrot.knowledge.wiki.ledger.store import LedgerStore  # verified: wiki/ledger/store.py:24
from parrot.knowledge.wiki.ledger.service import LedgerService  # verified: wiki/ledger/service.py:140,164
from parrot.knowledge.wiki.schema.store import SchemaStore  # verified: wiki/schema/store.py:48
from parrot.knowledge.wiki.schema.models import ColumnRecord  # verified: wiki/schema/store.py:8 (import site)
from parrot.knowledge.wiki.schema.service import SchemaPlaneService  # verified: wiki/schema/service.py:66,82
from parrot.knowledge.wiki.federation import open_namespace_store  # verified: wiki/federation.py:362
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence  # verified: graphindex/persist_sqlite.py:138
from parrot.knowledge.graphindex.persist import GraphIndexPersistence  # verified: graphindex/persist.py:213
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence  # verified: graphindex/persist_postgres.py:207
from parrot.knowledge.graphindex.publish import GraphPublisher  # verified: graphindex/publish.py:37,47
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit, make_stub_tenant_context, HashingGraphEmbedder, DEFAULT_DIMENSION  # verified: graphindex/factory.py:197,45,116,41
from parrot.knowledge.graphindex.loader import GraphIndexLoader  # _make_persistence verified: graphindex/loader.py:288
from parrot.knowledge.graphindex.schema import UniversalNode, UniversalEdge, GraphUpdate, CommitReceipt, AssertionMeta  # verified: graphindex/schema.py:149,184,233,269,100
from parrot.knowledge.ontology.schema import TenantContext, MergedOntology  # verified: ontology/schema.py:529,452
from parrot.knowledge.ontology.graph_store import OntologyGraphStore  # verified: ontology/graph_store.py:53
from parrot.knowledge.pageindex.hybrid_search import HybridPageIndexSearch  # verified: pageindex/hybrid_search.py:73
from parrot.knowledge.pageindex.store import JSONTreeStore  # verified: pageindex/store.py:23
from parrot.knowledge.pageindex.content_store import NodeContentStore  # verified: pageindex/content_store.py:38
from parrot.knowledge.pageindex.embedding_store import NodeEmbeddingStore  # verified: pageindex/embedding_store.py:42
from parrot.knowledge.bookstore.catalog import CatalogStore  # verified: bookstore/catalog.py:163
from parrot.knowledge.bookstore.models import BookCard, BookRelation, BookCommunity  # used by catalog.py:286,484,665 (row mappers)
from parrot._imports import lazy_import  # verified: parrot/_imports.py:110
# external (after the extra is installed) — verified against the unpacked helix_db-0.3.4 wheel:
from helixdb import AsyncClient, Disk, InMemory, HelixError, IndexSpec, Predicate, BatchCondition, VectorDistanceMetric, NodeRef, g, read_batch, write_batch, define_params, QueryRequest
# embedded runtime (only inside AsyncClient.embedded): import helixdb_uniffi  — verified: helixdb/client.py:281 (_native_helixdb)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):                                      # line 553
    supports_attrs: bool = False
    async def get_attrs(self, concept_id: str) -> dict[str, str]
    async def list_by_attrs(self, filters, *, date_key=None, since=None, until=None, limit=200) -> list[dict]
    async def upsert_attrs(self, concept_id: str, attrs, *, replace: bool = True) -> int
    # abstract: upsert_pages, add_edges, replace_source_slice, delete_page, upsert_embedding, get_page, list_pages,
    #           search_fts, search_vector, neighbors, dump_pages, dump_edges, stats, orphan_sources, broken_edges, missing_bodies
    async def rebuild_index(self) -> dict[str, Any]; async def index_drift(self) -> dict[str, int]
    async def compare_and_swap_page(self, page: WikiPageRecord, expected_content_hash: Optional[str]) -> bool   # line 680
    async def get_meta(self, key: str) -> Optional[str]; async def set_meta(self, key: str, value: str) -> None   # ~714/728
    def _assert_writable(self) -> None                                                                           # ~737
    async def upsert_symbols(...); symbols_for(rel_path); find_symbols(...); search_symbols_fts(query, limit=20)  # ~814-909
    async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]                              # ~930
class SQLiteWikiStore(BaseWikiStore):                          # line 948
    def __init__(self, db_path, wiki_name="", *, read_only=False, sqlite_policy=None, persistent_writer=False)
def create_wiki_store(storage_dir, wiki_name="", backend="sqlite", **kwargs) -> BaseWikiStore   # line 2665; branches :2707 sqlite, :2713 memory, :2719 arangodb, :2730 postgres, :2741 _EXTRA_BACKENDS

# wiki/project.py
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]      # line 76
class WikiNamespaceConfig(BaseModel)                                              # line 186 (backend doc :205-210)
class WikiProjectConfig(BaseModel):                                               # line 561
    backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite")     # line 605
    arango_database / arango_credentials_env / arango_text_analyzer                # lines 616-627
    body_max_chars: int = Field(default=16_000, ge=1_000)                          # line 608
    def graph_path(self, root: Path) -> Path                                       # line 721
def _env_credential(key: str, default: Any) -> Any                                # line 822
def resolve_arango_params(config: WikiProjectConfig) -> dict[str, Any]            # line 851

# wiki/sources.py — class SourceCollectionManager: __init__ :144, backend Literal :148, validation :184, _run_async :1224, _arango_* :1289-1395
# wiki/ledger/store.py — class LedgerStore(SQLiteWikiStore) :24; ledger_transaction(operation) -> AsyncIterator[aiosqlite.Connection] :54; read_cursor :75; upsert_pages_in :107; add_edges_in :116
# wiki/ledger/index.py — conn uses :128 (SELECT body), :157/:167/:189/:200/:210/:245 (upsert_pages_in/add_edges_in), :254-259 (ledger_state), :375-377 (DELETE ×3), :549 (SELECT by category)
# wiki/ledger/sdd_ingest.py — :99-102, :195-198
# wiki/schema/store.py — class SchemaStore(SQLiteWikiStore) :48; upsert_columns :120; columns_for :126; find_columns :135; replace_schema_slice :195; fold_ddl_table :226

# graphindex/persist_sqlite.py — class SQLitePersistence :138; __init__(db_dir) :153; persist_graph :263; replace_document_slice :341; is_stale :464; load_graph :574; apply_update :608; get_commit :785; list_commits :817; revert_commit :856
# graphindex/factory.py — build_graph_memory_toolkit(..., backend="sqlite", dsn=None, schema="graphindex") :197; dispatch :249-261
# graphindex/loader.py — __init__ sqlite_dir kwarg :151; _make_persistence :288 (sqlite :290-293, arango :313)
# graphindex/publish.py — class GraphPublisher :37; __init__(persistence: Any, ctx: TenantContext) :47
# ontology/graph_store.py — class OntologyGraphStore :53; __init__(arango_client=None) :69; initialize_tenant :91; execute_traversal(ctx, aql, bind_vars=None, collection_binds=None) :271; upsert_nodes :311; create_edges :411; get_all_nodes :488; soft_delete_nodes :517; ensure_collection :570; get_document :598; upsert_document :622; insert_document :650; remove_document :669; query_documents :697; get_all_edges :738; edges_incident :764; remove_edge_by_triple :791
# ontology callers of execute_traversal — authorization.py:257,339; entity_resolver.py:384,427; mixin.py:337,359,379
# pageindex/hybrid_search.py — class HybridPageIndexSearch :73 (__init__ … use_vec_rank=False :83); mark_dirty :119; _rebuild_bm25 :163; _bm25_rank(query, top_k) :177; _vec_rank(query, top_k) :199; _rrf_fuse :277; search :288
# pageindex/toolkit.py — JSONTreeStore :114; NodeContentStore :115; NodeEmbeddingStore :133
# bookstore/catalog.py — class CatalogStore :163; __init__(db_path) :171; supports_fts :269; upsert :300; remove :357; search(query, top_k=8) :409; upsert_relations :496; upsert_communities :680; set_card_community :730
# bookstore/library.py — self._catalogs[scope] = CatalogStore(...) :230; search_book :351; search :411
# wiki/cli.py — click.Choice(["sqlite","memory","arangodb"]) :670 and :1520; SQLitePersistence sites :4011, :4108, :4561, :4623
# wiki/runtime.py — SQLitePersistence(config.graph_path(root)) :91
# flows/dev_loop/graph_memory.py — SQLitePersistence(Path(db_dir)) :142
# parrot_tools — graphindex/flowtask.py:220 GraphIndexPersistence(graph_store=store); legal/wiki_store.py and legal/boe/sync.py instantiate OntologyGraphStore(
```

#### HelixDB SDK surface (helix-db 0.3.4 / helix-db-embedded 0.3.3 — read from the wheels, 2026-10-14)
```python
# helixdb/async_client.py
class AsyncClient:
    def __init__(self, url: str | None = None, *, api_key=None, timeout=None, limits: httpx.Limits | None = None, transport=None)
    @classmethod async def embedded(cls, source: HelixDbSource, *, cache=None) -> AsyncClient
    @classmethod async def embedded_reader(cls, source, *, cache=None) -> AsyncClient
    async def query(self, request: QueryRequest, *, timeout=None) -> Any
    async def execute(self, request: QueryRequest, **options) -> Any      # writer_only / warm_only (server only)
    async def close(self) -> None
# helixdb/client.py — @dataclass(frozen=True) InMemory(database: str) :161; Disk(root: str, database: str) :166; ObjectStorage :172; _native_helixdb() :281
# helixdb/_client_common.py — QUERY_PATH = "/v2/query"; HelixError(.network/.remote/.embedded/.embedded_unavailable)
# helixdb/dsl.py — read_batch() :3410; write_batch() :3414; g() :3054; IndexSpec :1284 (node_equality, node_unique_equality, node_range, node_text, node_vector);
#   Predicate :770; BatchCondition :3175 (var_not_empty/var_empty/var_min_size); ReadBatch.var_as_if :3271; WriteBatch.var_as_if :3358; VectorDistanceMetric :592;
#   Traversal ops: n, n_where, n_with_label, out, in_, both, out_e, in_e, add_n, add_e, set_property, remove_property, drop, drop_edge, drop_edge_by_id,
#   create_index_if_not_exists, drop_index, get_index_operation, create_text_index_nodes, create_vector_index_nodes, text_search_nodes, vector_search_nodes,
#   where, limit, skip, order_by, dedup, count, value_map, project, shortest_path, repeat, group_count, union
# helixdb_uniffi/helixdb.py — HelixDbSource.IN_MEMORY(database) / DISK(root, database) :3544; HelixDb :5560 (open/open_reader/query_json/graph/close)
# Server: image ghcr.io/helixdb/helixdb:v0.0.12, container port 8080, /healthz, /readyz, HELIX_DATA_DIR, uid 65532
# Limits: whole-index search cap 800; per-document text analysis 64 MiB / ~16k unique terms; queued index work per write 8 MiB; text/vector indexes on top-level properties only
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `HelixWikiStore` | `create_wiki_store()` | new `backend == "helixdb"` branch | `wiki/store.py:2730-2741` |
| `HelixWikiStore` | `open_namespace_store()` | built-in database-kind backend | `wiki/federation.py:362,418` |
| `resolve_helix_params` | `_env_credential` | env chain | `wiki/project.py:822,851` |
| `HelixLedgerStore` | `LedgerService.from_root/from_dir` | backend dispatch | `wiki/ledger/service.py:140,164` |
| `LedgerTxn` | `ledger/index.py`, `ledger/sdd_ingest.py` | `async with store.ledger_transaction(...)` | `index.py:276,359,440,477,511,548`; `sdd_ingest.py:99,195` |
| `HelixSchemaStore` | `SchemaPlaneService` | backend dispatch | `wiki/schema/service.py:66,82` |
| `HelixPersistence` | `GraphPublisher(persistence, ctx)` | duck-typed | `graphindex/publish.py:47` |
| `graphindex_persistence_for` | runtime / cli / dev_loop sites | replaces direct ctor | `wiki/runtime.py:91`; `wiki/cli.py:4011,4108,4561,4623`; `flows/dev_loop/graph_memory.py:142` |
| `HelixPersistence` | `build_graph_memory_toolkit`, `GraphIndexLoader` | `backend="helixdb"` / `helix_settings=` | `graphindex/factory.py:253`; `loader.py:290` |
| typed traversals | `authorization`, `entity_resolver`, `mixin` | method calls replacing `execute_traversal` | `authorization.py:257,339`; `entity_resolver.py:384,427`; `mixin.py:337,359,379` |
| `ontology_graph_store_for` | `GraphIndexLoader`, `parrot_tools` callers | factory | `graphindex/loader.py:313`; `parrot_tools/graphindex/flowtask.py:220` |
| `PageIndexHelixProjection` | `HybridPageIndexSearch._bm25_rank/_vec_rank` | delegation when set | `pageindex/hybrid_search.py:177,199` |
| `BookstoreHelixProjection` | `CatalogStore.search` / `Library` | delegation when set | `bookstore/catalog.py:409`; `library.py:230` |

### Does NOT Exist (Anti-Hallucination)
- ~~HelixQL `.hx` files, `helix compile` / `helix deploy`~~ — legacy workflow; v3 sends JSON operation trees to `POST /v2/query`.
- ~~`g().upsert(...)` / any HelixDB upsert op~~ — emulate with conditional entries (`var_as_if`) + `set_property` / `add_n`.
- ~~`AsyncClient.graph()`~~ — native graph algorithms exist only on the sync `Client.graph()`; not used here.
- ~~`AsyncClient.cypher()`, `/v2/cypher` in this feature~~ — out of scope (Q3).
- ~~`SearchConsistency` on Python 0.3.4 requests~~ — not available in this SDK version.
- ~~`parrot.knowledge.helix`, `HelixWikiStore`, `HelixPersistence`, `HelixOntologyGraphStore`, `HelixLedgerStore`, `HelixSchemaStore`, `PageIndexHelixProjection`, `BookstoreHelixProjection`, `LedgerTxn`, `graphindex_persistence_for`, `ontology_graph_store_for`, `resolve_helix_params`, `HELIXDB_*` settings~~ — all created by this feature.
- ~~A `BasePersistence` ABC for GraphIndex backends~~ — duck-typed (`GraphPublisher.__init__(persistence: Any)`).
- ~~`BaseWikiStore.close()` / `initialize()` abstract methods~~ — only concrete backends define them; consumers never call them generically.
- ~~A SQLite-backed PageIndex (`pageindex/*.db`)~~ — PageIndex is JSON + markdown + `.npy`.
- ~~A HelixDB driver in `asyncdb`~~ — none; the provider uses `helix-db` directly.
- ~~`docker/helixdb/`, Makefile `docker-helixdb`, extras `helixdb` / `helixdb-embedded`, a `helixdb-embedded` Makefile target~~ — the first three are created; the embedded target is deliberately **not** created (Q2).
- ~~`WikiNamespaceConfig.backend` Literal containing `"helixdb"`~~ — today free-form for satellite backends; this feature makes `"helixdb"` built-in.
- ~~`OntologyGraphStore.neighbours / find_entities / path_between`~~ — added by M8; today only `execute_traversal(aql)` exists.
- ~~`tests/knowledge/helix/`~~ — created by M11.

### Edit Sites (Blueprint Anchors)

Verified against: `246f1bb6d` (dev, 2026-10-14)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/helix/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/helix/settings.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/helix/client.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/helix/bootstrap.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/helix/dsl.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/helix/errors.py` | CREATE | — | — | — |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `graphindex-postgres = [` | `pyproject.toml:287` | 1 |
| `pyproject.toml` (root) | MODIFY | `    "pytest-timeout>=2.3",` (last entry of `dev`) | `pyproject.toml:75` | 1 |
| `ruff.toml` | MODIFY | `"packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py" = ["TID251"]` | `ruff.toml:163` | 1 |
| `docker/helixdb/Dockerfile` | CREATE | — | — | — |
| `docker/helixdb/docker-compose.yml` | CREATE | — | — | — |
| `docker/helixdb/README.md` | CREATE | — | — | — |
| `Makefile` | MODIFY | `docker-dev:` | `Makefile:920` | 1 |
| `Makefile` | MODIFY | `	@echo "    docker-whatsapp-bridge   - Build and run in Docker"` | `Makefile:1097` | 1 |
| `docs/wiki/cheatsheet.md` | MODIFY | `wikitoolkit build --backend arangodb # plano compartido en ArangoDB` | `cheatsheet.md:43` | 1 |
| `docs/wiki/helixdb.md` | CREATE | — | — | — |
| `sdd/state/FEAT-670/spike-embedded-two-writers.md` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/helix_store.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | `    if backend in _EXTRA_BACKENDS:` | `store.py:2741` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` | MODIFY | `        backend: Literal["sqlite", "json", "arangodb"] = "sqlite",` | `sources.py:148` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` | MODIFY | `        if backend not in ("sqlite", "json", "arangodb"):` | `sources.py:184` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` | MODIFY | `    storage_backend: Literal["sqlite", "memory", "arangodb"] = Field(` | `models.py:114` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `    backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite")` | `project.py:605` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `    arango_text_analyzer: str = Field(` | `project.py:624` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `def resolve_arango_params(config: WikiProjectConfig) -> dict[str, Any]:` | `project.py:851` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `    def is_built(self, root: Path) -> bool:` | `project.py:774` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `            object.__setattr__(self, "backend", "arangodb")` | `project.py:267` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | `            arango_params=resolve_arango_params(_arango_config_for(cfg)),` | `federation.py:425` (within :396-430) | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py`, `wiki/sync.py` | MODIFY | `"arangodb"` string checks (3 and 4 sites) — classify per S1; multi-occurrence, task quotes context | (counts verified; lines task-time) | 3 / 4 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `        type=click.Choice(["sqlite", "memory", "arangodb"]),` (inside `_store_options`, after `"backend_opt",`) | `cli.py:670` | 2 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `    type=click.Choice(["sqlite", "memory", "arangodb"]),` (top-level `build` option, after `"--backend",`) | `cli.py:1520` | 2 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `        persistence = SQLitePersistence(config.graph_path(root))` (3 sites: `:4011`, `:4561` nested at deeper indent, `:4623`) | `cli.py:4011,4561,4623` | 3 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `GraphPublisher(SQLitePersistence(config.graph_path(root)), ctx)` | `cli.py:4108` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/entity_cli.py` | MODIFY | `help="Backend (default: sqlite / WIKI_STORE_BACKEND)."` | `entity_cli.py:258,374,454` | 3 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py` | MODIFY | `        persistence = SQLitePersistence(config.graph_path(root))` | `runtime.py:91` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/graph_memory.py` | MODIFY | `        persistence = SQLitePersistence(Path(db_dir))` | `graph_memory.py:142` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py` | MODIFY | `    async def ledger_transaction(self, operation: str) -> AsyncIterator[aiosqlite.Connection]:` | `ledger/store.py:54` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/helix_store.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | `        async with self.store.ledger_transaction("ledger.sync") as new_conn:` | `index.py:276` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | `        async with self.store.ledger_transaction("ledger.rebuild") as conn:` | `index.py:359` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | `        async with self.store.ledger_transaction("ledger.claim") as conn:` | `index.py:440` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | `        async with self.store.ledger_transaction("ledger.close") as conn:` | `index.py:477` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | `        async with self.store.ledger_transaction("ledger.unclaim") as conn:` | `index.py:511` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | `        async with self.store.ledger_transaction("ledger.compact") as conn:` | `index.py:548` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py` | MODIFY | `            async with self.store.ledger_transaction("ledger.ingest.specs") as conn:` | `sdd_ingest.py:99` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py` | MODIFY | `            async with self.store.ledger_transaction("ledger.ingest.tasks") as conn:` | `sdd_ingest.py:195` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `        store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=policy)` | `service.py:140` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `        store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=sqlite_policy)` | `service.py:164` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `        async with self.store._read() as conn:` | `service.py:178,309,467` | 3 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | `    async def apply_event(self, event: LedgerEvent, conn: "aiosqlite.Connection") -> None:` | `index.py:103` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` | MODIFY | `    async def _read_issue(self, conn: "aiosqlite.Connection", issue_id: str) -> dict[str, Any] \| None:` | `index.py:126` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/helix_store.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py` | MODIFY | `        store = SchemaStore(` (in `from_root`, followed by a multi-line call) | `schema/service.py:66` | 2 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py` | MODIFY | `        store = SchemaStore(plane_dir / "schema.db", wiki_name="schema", read_only=read_only)` | `schema/service.py:82` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_helix.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persistence_resolver.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` | MODIFY | `    elif backend == "postgres":` | `factory.py:253` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py` | MODIFY | `        if self._sqlite_dir is not None:` | `loader.py:290` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` | MODIFY | `    async def execute_traversal(` | `graph_store.py:271` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/helix_graph_store.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/factory.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py` | MODIFY | `                results = await self._graph_store.execute_traversal(` | `authorization.py:257,339` | 2 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py` | MODIFY | `        return await self._graph_store.execute_traversal(` | `entity_resolver.py:384,427` | 2 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py` | MODIFY | `primary_result = await self._ont_graph_store.execute_traversal(` / `secondary_result = …` / `single_result = …` | `mixin.py:337,359,379` | 1 each |
| `packages/ai-parrot-tools/src/parrot_tools/graphindex/flowtask.py` | MODIFY | `        return GraphIndexPersistence(graph_store=store)` | `flowtask.py:220` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/legal/wiki_store.py` | MODIFY | `OntologyGraphStore(` | (unverified line — check before use) | ≥1 |
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/sync.py` | MODIFY | `OntologyGraphStore(` | (unverified line — check before use) | ≥1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/helix_projection.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` | MODIFY | `    def _bm25_rank(self, query: str, top_k: int) -> list[str]:` | `hybrid_search.py:177` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/hybrid_search.py` | MODIFY | `    def _vec_rank(self, query: str, top_k: int) -> list[str]:` | `hybrid_search.py:199` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `        self._store = JSONTreeStore(storage_dir)` | `toolkit.py:114` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/pageindex/toolkit.py` | MODIFY | `    def _persist(self, tree_name: str) -> None:` | `toolkit.py:237` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/helix_projection.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `            self._catalogs[scope] = CatalogStore(self._location(scope).db_path)` | `library.py:230` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `    async def search_book(self, book_id: str, query: str, top_k: int = 8) -> list[dict[str, Any]]:` | `library.py:351` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/library.py` | MODIFY | `    async def search(` | `library.py:411` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/catalog.py` | — | **not modified** (S7: projection lives in `Library`) | — | — |
| `packages/ai-parrot/tests/knowledge/helix/…` and the per-plane `test_helix_*.py` files listed in M11 | CREATE | — | — | — |

- `/sdd-task` MUST re-run `grep -c` for every row it uses; FEAT-540 and FEAT-633 may move these lines before task time.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Lazy optional import**: `create_wiki_store` imports `helix_store` inside the branch exactly like `arangodb` (`wiki/store.py:2719`) and `postgres` (`:2730`); `factory.py` likewise (`:254-259`). `parrot.knowledge.helix.client` guards `import helixdb` with `lazy_import("helixdb", package_name="helix-db", extra="helixdb")` and `helixdb_uniffi` with `extra="helixdb-embedded"`.
- **Env resolution**: `resolve_helix_params` copies `resolve_arango_params` (`project.py:851`): prefix from `helix_credentials_env`, each key through `_env_credential` (os.environ → navconfig → default). Never read `.env` directly.
- **Server precedent**: `ArangoDBWikiStore` (`wiki/arango_store.py:137`) is the model for `initialize()` / `close()` / `read_only` / symbols surface; `PostgresWikiStore` (`postgres_store.py:127`) for DSN defaults and lazy-import error text.
- **Sync bridges**: `SourceCollectionManager._run_async` (`sources.py:1224`) and the `_arango_*` branch (`:1289-1395`) are the template for the `_helix_*` branch and for the BookStore projection driven from the synchronous `CatalogStore`.
- **One batch per public write**; never two round-trips for a logical write. Reads project only the columns consumers expect (match `SQLiteWikiStore` row dicts key-for-key).
- **Bootstrap, not migration**: `ensure_plane` runs lazily on first use per store instance and is idempotent; never on import.
- **Errors**: map every `HelixError` at the client wrapper; backends raise `HelixUnavailable` / `HelixWriteRejected` / `PermissionError` (read-only) only. Hook paths (`wikitoolkit upsert --changed`) treat `HelixUnavailable` like `WikiStoreBusy`: log, exit 0.
- **Typed traversals first**: derive each method's semantics from the AQL it replaces (cite the call site in the task), keep the AQL inside `OntologyGraphStore`, never a string query in a caller.
- **Projections are opt-in**: `PageIndexToolkit` / `Library` build a projection only when settings resolve AND the plane config enables it; absent projection ⇒ byte-identical legacy behaviour.
- **Tests**: embedded `InMemory` with a per-test database name; `pytest.importorskip("helixdb_uniffi")` at module top; live tests `pytest.mark.live` + reachability skip.
- Conventions: Google docstrings, strict typing, `self.logger`, Pydantic v2, 120 cols; `aiohttp` for the readiness probe (never `httpx` outside `helix/client.py`).

### Known Risks / Gotchas
- **FEAT-540 / FEAT-633 overlap** (user decision: proceed): TASK-3266/3267 touch `graphindex/loader.py` and `ontology/graph_store.py`; TASK-4092/4093 touch `wiki/store.py:1107-1497` and `project.py:38-110`. Every `/sdd-task` blueprint re-greps its anchor; merge conflicts are expected and resolved at merge time, not avoided.
- **No upsert in HelixDB**: forgetting the conditional entry produces duplicate nodes; the unique equality index then blocks the write with `unique violation` — treat as a bug, never retry blindly ("Do not retry a write automatically unless the full request is safe to replay", HelixDB docs).
- **Multigraph edges**: every `add_e` without the find-first helper duplicates edges; lint `broken_edges`/`index_drift` must count duplicates.
- **Async index DDL**: a search right after `create_*_index*` returns nothing until the backfill is active; `ensure_plane` must poll receipts (`get_index_operation`) and the bootstrap timeout (`index_ready_timeout_s`) must be generous on the first build of a large plane.
- **Text admission limits**: per document ~64 MiB analysis / ~16k unique terms, 8 MiB queued text per write; `search_text` is truncated to `body_max_chars` and batches split at ~4 MiB of text. Rejections are `HTTP 400 active_text_mutation_limit_exceeded` and abort the whole batch.
- **Result cap 800** on whole-index text/vector searches; `limit` is clamped and the clamp is logged at debug.
- **Single-writer embedded engine**: two embedded writers on one `Disk` source is unsupported; the M2 spike records the exact error for the guard message. Local multi-process use goes through the server (Round 2a).
- **`strong` consistency default** keeps read-after-write correct; `SearchConsistency` cannot be set from Python 0.3.4, so no "eventual" tuning in this feature.
- **Server image is v0.0.x**: index-storage version bumps are one-way (v0.0.10 → v5); the README backup procedure is mandatory before changing `HELIXDB_IMAGE_TAG`.
- **Native wheel**: `helix-db-embedded` is manylinux_2_28; the CI runner and dev images must satisfy glibc ≥ 2.28 (Ubuntu ≥ 20.04). macOS/Windows wheels exist; no `musl`.
- **`httpx` in the tree**: only `helix/client.py` is exempted; `test_extras_and_ruff_exemption` guards against drift. `AsyncClient` only — the sync `Client` would block the loop.
- **Ledger hard cut**: `wikitoolkit ledger` is used by `/sdd-done` and `/sdd-fix`; the SQLite `LedgerTxn` must be behaviour-identical (same `_write(operation)` + busy-timeout semantics) — covered by `test_ledger_txn_sqlite_and_helix_parity`.
- **Ontology authorization**: M8 changes a security-sensitive module; the typed methods must reproduce the AQL filters exactly (tenant scoping, soft-delete flags). Adversarial review (`/sdd-codereview`) is mandatory for M8 tasks.
- **PageIndex ranking parity** is set-equality on top-k, not order equality: HelixDB's BM25 analyzer differs from `bm25s` tokenisation (stopwords="en"); AC8 is deliberately set-based.
- **Switching a backend is not a migration** (design-research S11): the OKF export (`wiki/export.py:130`) is a pages/edges projection, not full fidelity (attrs, symbols, meta, embeddings, source state are not exported). Pointing `backend: helixdb` at an existing project opens an **empty** plane; the documented path is a canonical-source rebuild per plane (AC23). A cross-backend copy tool is §8 Q2.
- **Cross-client edge races** (S5): HelixDB has no unique edge index. Within one request the find-or-add helper is atomic; across two HTTP clients a duplicate `edge_key` is possible. `GraphPublisher` writes are already serialised per tenant in-process; cross-process duplicates are detected by `index_drift` / `broken_edges` lint and repaired by `rebuild_index` (dedupe by `edge_key`).
- **Template-driven ontology traversals** (S3): `TraversalPattern.query_template` is open-ended AQL declared in ontology YAML; `HelixOntologyGraphStore` cannot run it. Until §8 Q1 is decided, such patterns are ArangoDB-only and raise `UnsupportedTraversal` on HelixDB.

### Configuration References (navconfig / env)
| Key | Default | Used by |
|---|---|---|
| `HELIXDB_URL` | `http://127.0.0.1:6969` | server mode |
| `HELIXDB_API_KEY` | unset | server mode (bearer) |
| `HELIXDB_MODE` | `server` | overrides `WikiProjectConfig.helix_mode` |
| `HELIXDB_IMAGE_TAG` | `v0.0.12` | `docker/helixdb/docker-compose.yml` |
| `HELIXDB_PORT` | `6969` | compose published port |
| `WIKI_STORE_BACKEND` | — | existing; now accepts `helixdb` |
| `.parrot/wiki.json` → `backend`, `helix_database`, `helix_credentials_env`, `helix_mode` | `sqlite`, `wiki_<name>`, `HELIXDB`, `server` | `WikiProjectConfig` |

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `helix-db` | `==0.3.4` | Python SDK: `AsyncClient`, DSL, index specs (`extra: helixdb`; also root `dev` group) |
| `helix-db-embedded` | `==0.3.3` | native UniFFI runtime for embedded `InMemory` / `Disk` (`extra: helixdb-embedded`; root `dev` group for CI) |
| `httpx` (transitive of `helix-db`) | `<1,>=0.28.1` | transport of `AsyncClient`; confined to `helix/client.py` via `TID251` per-file ignore |
| `ghcr.io/helixdb/helixdb` | `v0.0.12` (pinned via `HELIXDB_IMAGE_TAG`) | standalone server for local multi-process and shared deployments |
| `aiohttp` (existing) | — | `/readyz` readiness probe |

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-670-helixdb-provider`; the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (evidence in §3 "Depends on"):
  - M1 → (nothing). Everything imports `parrot.knowledge.helix`.
  - M2 → M1 only for the README smoke command; otherwise independent (docker/Makefile/docs/spike).
  - M3 → M1 (`HelixClient`, `ensure_plane`, DSL helpers).
  - M4 → M1 (`HelixSettings`), M3 (`HelixWikiStore` for the `create_wiki_store` branch and CLI resolution).
  - M5 → M3 (subclasses `HelixWikiStore`), M4 (`LedgerService` dispatch on `WikiProjectConfig.backend`).
  - M6 → M3, M4.
  - M7 → M1, M4 (`graphindex_persistence_for` reads `WikiProjectConfig.backend`).
  - M8 → M1; M7 only for shared label helpers (soft edge — may be dropped at task time).
  - M9 → M1. M10 → M1.
  - M11 → all.
  Concurrent after M1: {M2, M3, M7, M8, M9, M10}; after M3+M4: {M5, M6}.
- **Shared files** (tasks serialized): `wiki/project.py` (M4 fields + `resolve_helix_params`), `wiki/cli.py` (M4 choices + M7 resolver sites), `graphindex/loader.py` (M7 `helix_settings` + M8 `ontology_graph_store_for`), `graphindex/factory.py` (M7 only), `wiki/store.py` (M3 branch only). M4 is a single **exclusive** task.
- **Exclusive resources**: root `pyproject.toml` / `uv.lock` (M1 adds dev-group wheels — `uv lock` once, `parallel: false`); `ruff.toml` (M1); `Makefile` (M2).
- **Cross-feature dependencies**: none required (user decision). Merge-time checks: FEAT-540 (`graphindex-core-seams`, TASK-3256..3268), FEAT-633 (`parrot-installer`, TASK-4092/4093), FEAT-481 (`fireflies-wiki-knowledgebase-agent`, wiki ingest).

---

## 8. Open Questions

### Resolved (carried from the brainstorm — do not re-open)

- [x] Vector index dimension strategy — *Resolved in brainstorm*: lazy per-dimension index. The first vector written for a label creates the property `embedding_<dim>` and its cosine vector index; a later vector of another length creates a sibling property/index; `search_vector()` selects the index matching the query vector's length. No new config field. → §2 Data-model mapping, M1 `ensure_vector_index`, AC10.
- [x] Makefile "embedded" target semantics — *Resolved in brainstorm*: dropped. Only `make docker-helixdb` (server) is added; embedded stays a test fixture with no Makefile entry. → M2, AC12, Non-Goals.
- [x] Cypher availability — *Resolved in brainstorm*: out of scope, never probed. Typed traversal methods on `OntologyGraphStore` are mandatory; ArangoDB keeps AQL inside them, HelixDB uses the DSL. → M8, Non-Goals, AC7.
- [x] Multi-process embedded `Disk` behaviour — *Resolved in brainstorm*: keep a 30-minute spike in M0 whose only output is the observed error class when a second process opens a writer, used to word the `helix_mode=embedded` guard message and the docs. → M2 spike file, AC13.
- [x] `LedgerStore.ledger_transaction()` reshaping — *Resolved in brainstorm*: hard cut. `ledger_transaction()` yields a backend-neutral `LedgerTxn` accumulator (`upsert_pages`, `add_edges`, `set_state`); the SQLite implementation wraps the connection, the HelixDB one collects a single `write_batch`. All call sites in `wiki/ledger/` are updated in-feature, no shim. → M5, AC5.
- [x] CI native wheel — *Resolved in brainstorm*: install `helix-db-embedded` in CI (test extras / uv dev group); unit tests run on embedded `InMemory` on every PR. Live server tests stay gated on `HELIXDB_URL` reachability. → M1 dev group, M11, AC15.
- [x] Tenancy mapping for GraphIndex — *Resolved in brainstorm*: one HelixDB database per tenant — server database `gi_<tenant>`, embedded `Disk(root, tenant)`. Mirrors `<tenant>.db` and ArangoDB's `db_<tenant>`; no `tenant_id` filters in queries. → §2, M7.
- [x] ArangoDB retirement — *Resolved in brainstorm*: there is no retirement. HelixDB is an additional supported backend; `ArangoDBWikiStore`, `GraphIndexPersistence` (ArangoDB) and `docker/arango` stay first-class, with no deprecation warnings or doc pointers away from them. → Non-Goals, AC16.
- [x] Server image pin and upgrade policy — *Resolved in brainstorm*: compose reads `${HELIXDB_IMAGE_TAG:-v0.0.12}`; the README documents the one-way index-storage-version upgrade and a manual `HELIX_DATA_DIR` volume backup to run before changing the tag. Bumping the default tag is a reviewed manual change; no Makefile backup target. → M2, AC12.
- [x] Target version — *Resolved at spec time*: 1.3.0 (next minor).

### Unresolved

- [ ] **Q1 — Template-driven ontology traversals on HelixDB** (escalated from design research S3). `TraversalPattern.query_template` (`ontology/schema.py:288`) and `ResolvedIntent.aql` (`ontology/intent.py:42`) are open-ended AQL strings declared per ontology YAML and executed at `mixin.py:337/359/379`. Options: (a) add a validated, backend-neutral `traversal_spec` (start label/key, edge labels, direction, depth, filters, projection) to `TraversalPattern`, compiled to AQL on ArangoDB and to the DSL on HelixDB, with `query_template` kept as an ArangoDB-only escape hatch; (b) template patterns stay ArangoDB-only in this feature (`UnsupportedTraversal` on HelixDB) and a follow-up spec designs the traversal spec. M8's skeleton is written for (b) with (a) as an additive extension. — *Owner: Jesus Lara*
- [ ] **Q2 — Cross-backend copy tool** (escalated from design research S11). Rebuild-from-canonical-sources is documented (AC23). Should this feature also ship `wikitoolkit migrate --to helixdb` that copies pages, edges, attrs, symbols, meta and embeddings with counts, checkpoints and a verification report, for planes whose sources are no longer available (e.g. curated/learned pages, agent-written GraphIndex memory with commit history)? — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Model: `gpt-5.6-luna` (codex-cli 0.160.0, reasoning high, 2m37s) · Status: completed
> · Transcript: `sdd/state/FEAT-670/design_research/` (brief = brainstorm sections + 28 code paths only; no spec text)
> Reviewer summary: "The main risks are not the Helix data mapping itself, but incomplete backend seams, leaky existing contracts, and projection consistency." Every `affected_paths` entry passed containment + `test -e`; every factual claim was re-read in the source before disposition.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Centralize backend opening behind a capability-aware resolver (architecture) | CONFIRM | Verified: `is_built()` (`project.py:785-788`) handles only sqlite/arangodb then falls through; `"arangodb"` literal checks: cli 15, toolkit 3, sync 4, federation 4, sources 20 | §3 M4 (`SERVER_BACKENDS`, `is_server_backend`, `is_built`), AC19 |
| S2 | Replace the ledger connection leak with a repository transaction protocol (architecture) | CONFIRM | Verified: `LedgerService` uses `store._read()` at `:178,309,467`; `LedgerIndex.apply_event/_read_issue` typed `aiosqlite.Connection` (`index.py:103,126,136`) | §3 M5 (`LedgerReader`, `ledger_read()`, retyped index methods), AC5, `test_ledger_reader_protocol` |
| S3 | Constrain ontology traversal before removing raw AQL (architecture) | ESCALATE | Verified: `TraversalPattern.query_template` (`schema.py:288`) and `ResolvedIntent.aql` (`intent.py:42,150,212,220`) are open-ended AQL; named methods cannot absorb them — the YAML-contract decision is the user's | §8 Q1; M8 scope caveat + `execute_pattern` / `UnsupportedTraversal` |
| S4 | Make GraphIndex backend selection explicit and mutually exclusive (api) | CONFIRM | Verified: `loader.py:290-313` picks sqlite when `_sqlite_dir` else arango; factory documents only sqlite/postgres | §3 M7 precedence rule, AC20, `test_loader_backend_precedence` |
| S5 | Specify atomic commit ordering, edge identity, revert conflict semantics (risk) | CONFIRM | Verified: SQLite edge PK `(source_id, target_id, kind)` (`persist_sqlite.py:73`), revert conflict by `rowid` (`:898-908`); HelixDB has no unique edge index | §3 M7 (`edge_key`, `seq` on Meta, pre-images incl. incident edges), §7 risk, AC21 |
| S6 | Generation-based PageIndex projection or durable outbox (risk) | CONFIRM | Verified: `splice_subtree` → `reindex_node_ids` (`tree_ops.py:89-141`) before `_save_node_markdown` / `_persist` (`toolkit.py:851-980,237`) | §3 M9 redesigned (generation per `_persist`, fallback on mismatch), AC22 |
| S7 | Put BookStore's async Helix adapter below the async Library boundary (api) | CONFIRM | Verified: `CatalogStore` is sync with short-lived `sqlite3` connections (`catalog.py:9-19,183`); `Library.search` is async (`library.py:411`) | §3 M10 redesigned (projection owned by `Library`; `catalog.py` unmodified; stale-fallback policy), AC22 |
| S8 | Add generic backend connection settings and fix namespace dispatch (api) | CONFIRM | Verified: only `arango_*` fields (`project.py:616-627`); validator coerces `database` → arangodb (`:267`); federation passes `arango_params` to extra factories (`federation.py:425`) | §3 M4 (validator + `open_namespace_store` dispatch), §2 `HelixSettings`, AC19 |
| S9 | Build a backend contract matrix rather than only live-server smoke tests (testing) | CONFIRM | Existing suites are per-backend copies (`test_store_cas.py`, `test_postgres_store_cas.py`, `test_arango_store_cas.py`) | §3 M11 (`wiki_store_matrix`), §4 |
| S10 | Add a compatibility gate for the SDK, embedded wheel and pinned image (testing) | CONFIRM | SDK 0.3.4, wheel 0.3.3 and image v0.0.12 are independently versioned (release notes show image/SDK cadences differ) | §3 M11 `test_compat_gate.py`, AC24 |
| S11 | Define migration and rollback before exposing a backend switch (risk) | CONFIRM (docs + rebuild) / ESCALATE (copy tool) | Verified: `export_okf_bundle` (`export.py:130`) exports pages/edges only; ledger canonical = event log (`ledger/log.py`); GraphIndex commits carry pre-images | §7 risk, AC23, `test_rebuild_from_canonical_sources`; copy tool → §8 Q2 |
| S12 | Preserve existing search filtering and score semantics explicitly (testing) | CONFIRM | Verified: archive exclusion (`store.py:2328-2362`), cosine score in [-1,1] (`store.py:2381`), Postgres `1 - distance` (`postgres_store.py:700-714`) | §3 M3 `search_fts` / `search_vector` contracts, AC18, `test_search_fts_archive_default_and_score_scale` |

Summary: **10** confirmed · **0** rejected · **2** escalated (S3 → Q1, S11 copy-tool → Q2).

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-14 | Jesus Lara (with Claude) | Initial draft from the accepted brainstorm (FEAT-670 reserved) |
| 0.2 | 2026-10-14 | Jesus Lara (with Claude) | Design research folded in: 10 confirmed (M3/M4/M5/M7/M9/M10/M11 contracts, AC18–AC24), 2 escalated (§8 Q1, Q2) |
