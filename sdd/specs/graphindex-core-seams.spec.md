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
tags: [graphindex, wiki, ontology, graph-store, import-seams, mcp]
---

# Feature Specification: GraphIndex Core Seams

**Feature ID**: FEAT-540
**Date**: 2026-09-09
**Revised**: 2026-10-14 against `dev` @ `246f1bb6d` (`packages/` identical to `origin/dev` @ `048479633`)
**Author**: Jesus Lara (with Claude); 2026-10-14 current-code review by Codex (v0.3), design-research cross-check by Codex (§9)
**Status**: review
**Target version**: 1.1.0

> **Phase 1 of 2: cut framework seams inside the existing workspace.**
> FEAT-541 (`parrot-graphindex-package`) owns the physical package move,
> distribution metadata and the old-package redirector. It depends on this
> feature. Source: `sdd/proposals/parrot-graphindex-standalone.brainstorm.md`
> (Option B).
>
> **v0.4 widens the scope** (owner decision, 2026-10-14): besides the import
> seams, this feature makes the graph persistence of the knowledge planes
> **graph-database agnostic and pluggable** — one explicit contract plus a
> registry for GraphIndex persistence backends, and a backend-neutral ontology
> graph-store contract with typed traversals so that raw AQL stops being the
> public surface. The HelixDB backend (`sdd/proposals/helixdb-provider
> .brainstorm.md`, FEAT-670 reserved 2026-10-14) plugs into these seams; it
> is **not** implemented here. That brainstorm's "ignore FEAT-540" constraint
> is reversed by this revision: FEAT-670 depends on M7/M8 of this spec.
>
> The 13 tasks of the September decomposition (TASK-3256…3268, all
> `pending`, no worktree) are **superseded** by this revision — see §10.

---

## 1. Motivation & Business Requirements

### Problem Statement

`wikitoolkit` (LLM wiki) and GraphIndex are the parts of AI-Parrot a developer
can use *without* an agent: point them at a repository, run `wikitoolkit
build`, and get a queryable knowledge graph plus a local MCP server for Claude
Code / Codex. Today that use case is impossible without installing the whole
framework: core declares **59 runtime dependencies** and a `parrot.conf`
settings module with import-time side effects (Navigator startup banner,
settings-directory resolution).

**Two couplings block it.**

**(a) Import coupling.** The graph code crosses a handful of eager package
roots and provider modules to fetch a Pydantic model, an exception class or a
concrete adapter. Fresh subprocess measurements (Python 3.12.3, this venv,
`artifacts/logs/FEAT-540-review-imports.json`, 2026-10-14; counts include the
probe's `importlib`/`sys`/`json`):

| Entry point | Modules today | Target ceiling | Forbidden packages loaded today |
|---|---:|---:|---|
| `parrot` | 99 | informational | none — the root is clean |
| `parrot.auth.exceptions` | 1093 | **150** | navconfig, parrot.conf, navigator_eventbus, asyncdb, faiss, redis, asyncpg |
| `parrot.knowledge.ontology.schema` | 1515 | **240** | the seven above + pandas, pyarrow |
| `parrot.knowledge.graphindex` | 1877 | **800** | same nine |
| `parrot.knowledge.graphindex.builder` | 1986 | **1200** | same nine |
| `parrot.knowledge.wiki.cli` | 2202 | **850** | same nine |

The gateways are unchanged since v0.2 and re-verified: `parrot/auth/__init__.py`
eagerly imports `.pbac` (`pbac.py:30` → `parrot.conf` → navconfig/redis) to
serve an exception module whose only import is `typing`;
`ontology/__init__.py:5` eagerly imports `.mixin`, which reaches
`parrot.auth.exceptions` (`mixin.py:65`); `stores/__init__.py:5` imports
`.abstract`, whose line 7 is `from navconfig.logging import logging`;
`graphindex/embed.py:15-20` imports `EmbeddingRegistry`, calls
`quiet_faiss_loader()` and imports `faiss` at module level;
`graphindex/builder.py:55` imports the concrete `PageIndexToolkit`;
`graphindex/pg_schema.py:19-23` imports `asyncpg`, `navconfig`, `pgvector`
and `parrot.conf` and resolves the DSN at import; `wiki/cli.py:46`,
`schema/render.py:14` and `schema/producers/ddl.py:13` import a plain dict
through `parrot.tools.sql_dialects`, which boots the tools package. The
September per-seam attribution (`exp-lazy-ontology`, `c4555d7d1`) is
superseded by these numbers.

**(b) Graph-store coupling.** Every knowledge plane that persists a graph
talks to its database in its own way, and the ArangoDB paths are written in
AQL at the call site:

| Plane | State on `dev` | Evidence |
|---|---|---|
| GraphIndex persistence | Three backends (`SQLitePersistence`, `PostgresPersistence`, Arango `GraphIndexPersistence`) plus the loader's private `_NullPersistence`, **duck-typed** — no shared contract, no registry; selection hard-coded at seven sites; Postgres-only extensions discovered by `hasattr` | `publish.py:47` (`persistence: Any`); `factory.py:249-261` accepts only `sqlite`/`postgres`; `loader.py:288-313` builds `AsyncDB("arangodb") → OntologyGraphStore → GraphIndexPersistence`; `wiki/runtime.py:91`, `wiki/cli.py:4011,4108,4561,4623`, `flows/dev_loop/graph_memory.py:142` instantiate `SQLitePersistence` directly; `parrot_tools/graphindex/toolkit.py:306,1326` probe `as_of`/`hybrid_retrieve` with `hasattr`; `contracts/temporal.py:361-375` calls the Postgres-only temporal surface; `retrieval/pin.py:416` reads `SQLitePersistence._db_path` |
| Ontology graph store | `OntologyGraphStore` is ArangoDB-only; its public surface is `execute_traversal(ctx, aql, …)` | 7 core call sites compose AQL inline: `authorization.py:257,339`, `entity_resolver.py:384,427`, `mixin.py:337,359,379` (the mixin runs AQL from `ResolvedIntent.aql`, which is either an ontology-YAML `TraversalPattern.query_template` or **LLM-generated** AQL validated by a regex, `intent.py:222`); 12 `parrot_tools` call sites: `legal/wiki_store.py` ×8, `legal/boe/queries.py:72,176`, `procedures/retrieval.py:292`, `contracts/retrieval.py:719` |
| Wiki retrieval plane | Already pluggable (`BaseWikiStore` + `register_wiki_backend`, used by `parrot_tools.legal`), but backend names are frozen in Pydantic `Literal`s and the source-collection manager keeps a private AQL branch | `wiki/models.py:114`, `project.py:605,1063`, `sources.py:148`; `sources.py:1303-1425` (11 AQL operations) and `wiki/toolkit.py:139-161` select the source backend by name |

Integrating a new graph database (HelixDB is the concrete candidate) would
otherwise fork every one of those paths. Out of scope but recorded:
`parrot/interfaces/hierarchy.py` holds 15 direct AQL calls outside the
knowledge tree.

### Goals

- **G1** — Every entry point in the table above meets its ceiling in a fresh
  subprocess, with none of `navconfig`, `parrot.conf`, `navigator_eventbus`,
  `asyncdb`, `pandas`, `faiss`, `pyarrow`, `redis`, `asyncpg` (root or
  dotted submodule) in `sys.modules`.
- **G2** — Nothing under `parrot/knowledge/wiki/` or `parrot/knowledge/
  graphindex/` imports `parrot.tools.*`, `parrot_tools`, `parrot.clients.*`,
  `parrot.loaders.*`, `parrot.stores.*`, `parrot.embeddings.*`, `parrot.conf`
  or a concrete PageIndex adapter/toolkit at module level (executable
  module-level branches included; only `TYPE_CHECKING` blocks exempt).
- **G3** — Framework capability is preserved exactly: agents keep real
  embedders, a real LLM adapter, a real PageIndex toolkit and the Arango/
  Postgres planes — injected through Protocols, never imported by the graph
  tree. Hashing stays the offline embedder default.
- **G4** — Framework tools and the SDK MCP transport share plain operations,
  input schemas and result serialization; the complete current tool surface
  (core, lint, standup, ledger, structural, decisions, schema, bulk/sync,
  vault) is preserved name-for-name and schema-for-schema.
- **G5** — Local and remote-proxy stdio MCP run with `parrot.mcp`,
  `parrot.tools` and `parrot_tools` blocked; the framework stdio path and the
  HTTP `serve.py` lifecycle keep working.
- **G6** — After this spec the graph tree is `git mv`-shaped for FEAT-541,
  with an audited inventory of every remaining function-local optional
  framework import.
- **G7** *(new)* — Every GraphIndex persistence backend satisfies one explicit
  base contract with specified semantics; optional capabilities (temporal,
  embeddings, hybrid retrieval, incremental staleness) are explicit
  Protocols; backends are selected through one registry/factory and no
  consumer branches on a backend name or probes with `hasattr`.
- **G8** *(new)* — The ontology graph store has a backend-neutral contract:
  typed operations for every traversal core code performs, a lower-level
  document/edge contract for GraphIndex's Arango persistence, declared
  traversal patterns keyed by query dialect, and a dialect-explicit dynamic
  query path that fails closed. ArangoDB keeps working unchanged behind it.

### Non-Goals (explicitly out of scope)

- Creating `packages/parrot-graphindex/`, the `parrot_graphindex` import name,
  the `sys.meta_path` redirector, or any change to dependency declarations /
  extras. FEAT-541.
- Implementing the HelixDB backend, its docker stack, extras or projections.
  FEAT-670 (`helixdb-provider`).
- Migrating wiki/graph/ledger/schema databases or bumping their schema
  versions; existing planes must reopen unchanged.
- Replacing drivers (`asyncdb` stays behind Arango; `asyncpg`+`pgvector`
  behind Postgres), changing retrieval/scoring semantics, or fixing
  unrelated backend limitations.
- Porting AQL to Cypher, or making `parrot/interfaces/hierarchy.py`
  backend-neutral.
- Renaming `TenantContext.arango_db` / `pgvector_schema` (escalated, §8 Q1).
- Moving `parrot/interfaces/obsidian/`, `parrot/interfaces/jira/` or all of
  PageIndex. FEAT-541 keeps the agreed split: pure tree/build/store code
  moves; `toolkit.py`, `llm_adapter.py`, `loader.py`, `pdf_to_markdown.py`
  remain framework adapters.
- Brainstorm Option C (slim core in place) and Option D (vendor into a
  separate repo) remain rejected.

---

## 2. Architectural Design

### Overview

Every place where graph code reaches into the framework — or into a specific
database — is replaced by one of four seams:

1. **Lazy package roots (PEP 562)** — `parrot/auth/__init__.py`,
   `parrot/knowledge/ontology/__init__.py`, `parrot/stores/__init__.py` and
   `parrot/knowledge/graphindex/__init__.py` keep every public name (`__all__`
   + `__dir__`) but resolve the expensive ones through a module-level
   `__getattr__`. `extend_path` and `supported_stores` stay eager.
2. **Provider Protocols** — `graphindex/protocols.py` declares `Embedder`,
   `LLMCaller` and `PageIndexer` as `typing.Protocol`s mirroring the exact
   subset graph code calls; `GraphIndexEmbedder` becomes a framework adapter
   under `parrot/embeddings/`; resolution order is explicit provider →
   built-in default → `ProviderNotAvailable`.
3. **Relocation over plain operations** — every `AbstractTool`/
   `AbstractToolkit` wiki wrapper moves to `parrot_tools/wiki/`; the
   framework-free operations, input schemas and result serialization they
   wrap stay in `parrot/knowledge/wiki/` and also feed the SDK MCP transport.
4. **Graph-store contracts + registries** *(new, M7/M8)* —
   `graphindex/protocols.py` also declares `GraphPersistence` (the base
   commit-protocol contract) and its capability Protocols;
   `graphindex/backends.py` is the single composition root
   (`register_graph_backend` / `create_graph_persistence`) with `sqlite`,
   `postgres`, `arangodb` and `null` registered lazily. On the ontology
   side, `ontology/contracts.py` declares `GraphDocumentStore` (collection/
   document/edge CRUD — what GraphIndex's Arango persistence needs) and
   `OntologyTraversalStore` (typed traversals, declared patterns, dialect-
   bound dynamic queries); today's class becomes `ArangoOntologyGraphStore`,
   implementing both, with its AQL kept private. Wiki backend names are
   validated against the wiki registry instead of `Literal`s, and the
   source-collection manager's AQL branch moves behind a `SourceManifestBackend`
   contract.

Two smaller seams support these: a single `resolve_setting()` configuration
reader (navconfig optional and lazy, `pg_schema.py` resolved at selection
time, the SQL dialect map moved to a neutral module), and framework-free
`GraphDocument` / `DocumentLoader` shapes with `GraphIndexLoader` relocated to
`parrot/loaders/`.

**Resolved in the brainstorm and binding**: navconfig stays an optional, lazy
credential provider; `asyncdb` stays behind Arango; `HashingGraphEmbedder`
(`factory.py:116`) is the default `Embedder`; the PageIndex split keeps the
four adapter modules in core; two-feature phasing; no entry-point registry
before FEAT-541 (the in-process registries here are explicit `register_*`
calls, not entry points).

### Component Diagram

```
   ┌──────────────────────── ai-parrot core (framework side) ─────────────────────────┐
   │ parrot.embeddings.graphindex.GraphIndexEmbedder (adapter, faiss + registry)      │
   │ parrot.knowledge.pageindex.llm_adapter.PageIndexLLMAdapter                       │
   │ parrot.knowledge.pageindex.toolkit.PageIndexToolkit                              │
   │ parrot.loaders.graphindex.GraphIndexLoader (AbstractLoader, framework Documents) │
   │ parrot.knowledge.ontology.graph_store.ArangoOntologyGraphStore (asyncdb, AQL)   │
   │ parrot.knowledge.graphindex.persist_arango.ArangoPersistence                    │
   │ parrot.knowledge.graphindex.persist_postgres.PostgresPersistence (asyncpg)      │
   └────────────────────────────┬──────────── injects / registers ───────────────────┘
                                ▼
   ┌──────────────── graph tree (framework-free after this spec) ─────────────────────┐
   │ graphindex/protocols.py   Embedder · LLMCaller · PageIndexer                     │
   │                           GraphPersistence (+ Incremental/Temporal/Embedding/    │
   │                           HybridRetrieval capabilities) · ProviderNotAvailable   │
   │ graphindex/backends.py    register_graph_backend · create_graph_persistence      │
   │                           built-ins: sqlite (persist_sqlite) · null · lazy        │
   │                           postgres / arangodb factories                           │
   │ ontology/contracts.py     GraphDocumentStore · OntologyTraversalStore            │
   │                           QueryDialect · DynamicQuery · register_ontology_backend │
   │ ontology/validators.py    register_query_validator · validate_query(dialect)     │
   │ graphindex/factory.py     wires providers + persistence through the registries   │
   │ GraphIndexBuilder · GraphPublisher · IngestTriageRouter · NoveltyScorer          │
   │ wiki/operations*.py       plain operations + input schemas (shared by both       │
   │                           transports) · wiki/transport.py descriptors            │
   │ wiki/project.py           resolve_setting() ──lazy──► navconfig (optional)       │
   │ wiki/sources_backend.py   SourceManifestBackend (sqlite · json · arangodb)       │
   │ wiki/mcp_server.py        transport=auto|framework|sdk · WikiToolBundle kept     │
   └────────────────────────────┬─────────────────────────────────────────────────────┘
                                │ plain operations / descriptors
                                ▼
   ┌──────────────── ai-parrot-tools (parrot_tools.wiki) ─────────────────────────────┐
   │ LLMWikiToolkit · CodeStructuralToolkit · DecisionToolkit · SchemaPlaneToolkit    │
   │ Wiki*Tool · Ledger*Tool · WikiLintTool · WikiStandupTool · Vault/Bulk/Sync tools │
   │ parrot_tools.graphindex.GraphIndexToolkit (isinstance(capability) instead of     │
   │ hasattr) · parrot_tools.legal / procedures / contracts (execute_pattern)          │
   └──────────────────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/auth/__init__.py:29-48` | modifies | PEP 562 root; every name stays resolvable; `.pbac` and friends load on first access |
| `parrot/knowledge/ontology/__init__.py:2-7` | modifies | PEP 562 root; `OntologyGraphStore` name is replaced by `ArangoOntologyGraphStore` (M8) |
| `parrot/stores/__init__.py:1-8` | modifies | PEP 562 root; `extend_path` + `supported_stores` eager |
| `parrot/knowledge/graphindex/__init__.py:16-61` | modifies | eager `communities`/`export_html`/`signals`/`persist_sqlite`/`projection`/`sqlite_reader`/`odoo_code` exports become lazy; `_LAZY_ATTRS` grows |
| `GraphIndexBuilder.__init__` (`builder.py:116-123`) | modifies | `persistence: GraphPersistence`, `embedder: Embedder`, `pageindex_toolkit: PageIndexer \| None`; `hasattr(…, "is_stale")` (`:505`) → `isinstance(…, IncrementalPersistence)` |
| `GraphIndexEmbedder` (`embed.py:25`) | moves | to `parrot/embeddings/graphindex.py` as an adapter; `pgvector_dsn` + stub `_persist_to_pgvector` (`:193`) removed (S8) |
| `signals.py:395,466,528,557`, `retriever.py:321` | modifies | typed against `Embedder` (`get_embedding`, `search_similar`) |
| `NoveltyScorer` (`triage.py:67`), `IngestTriageRouter` (`triage.py:243`) | modifies | accept `LLMCaller`; `triage.py:42` import removed |
| `inbox/classify.py:9,117`, `inbox/links.py:6,36`, `inbox/processor.py:15,58-59` | modifies | annotations → `LLMCaller` (TYPE_CHECKING for the concrete class) |
| `wiki/runtime.py:41-49,82-91,144-162` | modifies | provider construction through `llm_resolve`; persistence through `create_graph_persistence` |
| `PageIndexLLMAdapter` (`llm_adapter.py:42`), `PageIndexToolkit` (`toolkit.py:54`) | unchanged | satisfy `LLMCaller` / `PageIndexer` structurally |
| `GraphPublisher.__init__` (`publish.py:47`) | modifies | `persistence: GraphPersistence` |
| `build_graph_memory_toolkit` (`factory.py:197-261`) | modifies | dispatch replaced by `await create_graph_persistence(backend, **options)`; `embedder.index`/`_node_id_map` wiring (`:285-287`) moves to the framework adapter |
| `graphindex/loader.py:288-313` | moves + modifies | `GraphIndexLoader` → `parrot/loaders/graphindex.py`; `_make_persistence` → registry (`null` backend replaces `_NullPersistence`, `loader.py:44`) |
| `persist.py` → `persist_arango.py` | renames | `GraphIndexPersistence` → `ArangoPersistence(store: GraphDocumentStore)`; callers `builder.py:43`, `loader.py:40`, `parrot_tools/graphindex/flowtask.py:27,220`, tests |
| `persist_sqlite.py:138`, `persist_postgres.py:207` | modifies | declare conformance (no inheritance); add `close()` no-op to SQLite; Postgres `close()` (`:256`) unchanged |
| `wiki/cli.py:4011,4108,4561,4623`, `flows/dev_loop/graph_memory.py:142` | modifies | `create_graph_persistence("sqlite", db_dir=…)` |
| `parrot_tools/graphindex/toolkit.py:306,1326` | modifies | `isinstance(persistence, TemporalGraphPersistence / HybridRetrievalPersistence)` |
| `contracts/temporal.py:361-375` | modifies | typed `TemporalGraphPersistence`; unsupported backend → `CapabilityUnavailable` |
| `retrieval/pin.py:416` | modifies | explicit SQLite-only boundary: `isinstance` guard + clear error (S9) |
| `OntologyGraphStore` (`graph_store.py:53`) | renames + modifies | `ArangoOntologyGraphStore(GraphDocumentStore, OntologyTraversalStore)`; `execute_traversal` (`:271`) → private `_execute_aql`; typed ops added using the existing AQL verbatim |
| `authorization.py:257,339`, `entity_resolver.py:384,427`, `mixin.py:337-381` | modifies | typed operations / `execute_query(dialect=…)`; constructor types → `OntologyTraversalStore` |
| `TraversalPattern` (`schema.py:261-290`), `ResolvedIntent` (`schema.py:547-571`), `IntentDecision` (`intent.py:42`) | modifies | `query_templates: dict[str, str]`; `query` + `dialect` fields (hard cut of `aql`) |
| `validators.py:36` | modifies | `validate_query(dialect, text)` dispatch; AQL validator registered |
| `parrot_tools/legal/boe/queries.py:72,176`, `procedures/retrieval.py:292,311`, `contracts/retrieval.py:681,719` | modifies | `execute_pattern(ctx, pattern, params)`; `aql_for()` → `pattern_for()` |
| `parrot_tools/legal/wiki_store.py:209,265-486`, `legal/boe/sync.py:62` | modifies | construct `ArangoOntologyGraphStore`; inline AQL through `execute_query(…, dialect="aql")` — explicitly Arango-bound |
| `wiki/models.py:114`, `project.py:605,1063`, `sources.py:148` | modifies | `str` validated by `wiki_backend_names()`; built-ins registered in `store.py` |
| `federation.py:418`, `create_wiki_store` (`store.py:2665`), `wiki/toolkit.py:139-161` | modifies | one `resolve_wiki_backend()`; source backend via `create_source_backend()` |
| `sources.py:1303-1425` | moves | the 11 Arango operations → `wiki/arango_sources.py` implementing `SourceManifestBackend` |
| `wiki/project.py:792-851`, `wiki/cli.py:576`, `wiki/llm_resolve.py:11`, `graphindex/loader.py:337`, `pg_schema.py:19-23` | modifies | all readers fold into `resolve_setting()`; `pg_schema` resolves at backend selection |
| `wiki/cli.py:46`, `schema/render.py:14`, `schema/producers/ddl.py:13` | modifies | import the dialect map from `parrot/knowledge/common/sql_dialects.py`; `parrot/tools/sql_dialects.py:27` re-exports |
| `wiki/tools.py`, `toolkit.py`, `structural/{tools,toolkit}.py`, `decisions/{tools,toolkit}.py`, `schema/{tools,toolkit}.py` | moves | wrappers → `parrot_tools/wiki/`; operations + input models stay |
| `wiki/mcp_server.py:29,34,93-135,303,373-465`, `serve.py:156,196` | modifies | descriptors from the operation registry; `transport=` selector; `WikiToolBundle`/`abuild_wiki_tools`/`close_bundle` preserved |
| `parrot_tools/business_automation/memory.py:31,110` | modifies | repoint to `parrot_tools.wiki` |
| `parrot.mcp.local_server.StdioMCPServer` (`local_server.py:54`) | unchanged | framework transport |

### Data Models

```python
# parrot/knowledge/graphindex/models.py  (NEW — framework-free shapes)
from typing import Any, Protocol, runtime_checkable
from pydantic import BaseModel, Field

class GraphDocument(BaseModel):
    """Minimal document shape graphindex loaders need (page_content + metadata).

    Mirrors the two fields read from ``parrot.stores.models.Document``
    (`models.py:19-25`) without importing the stores package. The framework
    adapter converts in both directions; richer Document fields are not
    preserved and not claimed.
    """
    page_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)

@runtime_checkable
class DocumentLoader(Protocol):
    """What ``extractors/loader.py`` needs from a loader: ``load()`` only."""
    async def load(self) -> list[GraphDocument]: ...


# parrot/knowledge/ontology/schema.py  (MODIFIED — additive on patterns, hard cut on intents)
class TraversalPattern(BaseModel):                       # schema.py:261
    query_template: str                                  # schema.py:288 — AQL, kept as the "aql" entry
    query_templates: dict[str, str] = Field(default_factory=dict)
    """Dialect → template. ``query_template`` is the implicit ``"aql"`` entry;
    an explicit ``query_templates["aql"]`` wins over it."""

class ResolvedIntent(BaseModel):                         # schema.py:547
    query: str | None = None                             # was ``aql`` (schema.py:571) — hard cut
    dialect: str = "aql"                                 # NEW


# parrot/knowledge/ontology/contracts.py  (NEW)
class DynamicQuery(BaseModel):
    """A dialect-bound query text with its bind parameters (S5)."""
    dialect: str
    text: str
    bind_vars: dict[str, Any] = Field(default_factory=dict)
    collection_binds: dict[str, str] = Field(default_factory=dict)
```

### New Public Interfaces

```python
# parrot/knowledge/graphindex/protocols.py  (NEW — stdlib + pydantic-free runtime imports)
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class Embedder(Protocol):
    """Vector provider for graph nodes — the subset builder/retriever/signals call."""
    async def embed_nodes(self, nodes: list[Any], batch_size: int = 64) -> list[Any]: ...
    def get_embedding(self, node_id: str) -> Any | None: ...                       # signals.py:404
    async def search_similar(self, query: str, /, top_k: int = 10) -> list[tuple[str, float]]: ...  # retriever.py:321

@runtime_checkable
class LLMCaller(Protocol):
    """Mirror of PageIndexLLMAdapter.ask / ask_structured / ask_json (llm_adapter.py:61,99,201)."""
    async def ask(self, prompt: str, structured_output: Any = None, temperature: float = 0.0,
                  system_prompt: str | None = None) -> Any: ...
    async def ask_structured(self, prompt: str, output_type: Any, temperature: float = 0.0,
                             system_prompt: str | None = None) -> Any: ...
    async def ask_json(self, prompt: str, temperature: float = 0.0,
                       system_prompt: str | None = None) -> Any: ...

@runtime_checkable
class PageIndexer(Protocol):
    """The six PageIndexToolkit methods the extractors call (toolkit.py:404-857)."""
    async def list_trees(self) -> list[str]: ...
    async def create_tree(self, tree_name: str, doc_name: str | None = None) -> dict[str, Any]: ...
    async def delete_tree(self, tree_name: str) -> dict[str, Any]: ...
    async def get_tree(self, tree_name: str) -> dict[str, Any]: ...
    async def insert_markdown(self, tree_name: str, markdown: str, parent_node_id: str | None = None,
                              doc_name: str | None = None) -> dict[str, Any]: ...
    async def insert_ebook(self, tree_name: str, sections: list[Any],
                           parent_node_id: str | None = None) -> dict[str, Any]: ...

class ProviderNotAvailable(RuntimeError):
    """A required provider was never injected. ``role``, ``distribution``, ``extra`` name the fix; CLI exit 2."""
    def __init__(self, role: str, distribution: str, extra: str | None = None) -> None: ...

class CapabilityUnavailable(RuntimeError):
    """The selected graph backend does not implement an optional capability (temporal, hybrid, …)."""

# ── graph persistence (M7) ──
@runtime_checkable
class GraphPersistence(Protocol):
    """Base contract every GraphIndex backend satisfies (persist_sqlite.py:263-987 is the reference).

    Semantics (S2): ``apply_update`` is atomic — all items land or none; it returns a
    ``CommitReceipt`` whose ``seq`` is strictly monotonic per tenant; ``revert_commit``
    restores the captured pre-images and is itself a new commit; ``replace_document_slice``
    is atomic per ``document_uri`` and idempotent on identical input; ``load_graph`` returns
    the CURRENT graph (no soft-deleted items); a missing tenant store is created lazily by
    the first write and reads as empty, never as an error; backend errors propagate as the
    driver's exception — a backend never swallows them into an empty result.
    """
    async def persist_graph(self, ctx: Any, nodes: list[Any], edges: list[Any]) -> dict[str, Any]: ...
    async def replace_document_slice(self, ctx: Any, document_uri: str, nodes: list[Any],
                                     edges: list[Any]) -> dict[str, Any]: ...
    async def load_graph(self, ctx: Any) -> tuple[list[Any], list[Any]]: ...
    async def apply_update(self, ctx: Any, update: Any) -> Any: ...
    async def get_commit(self, ctx: Any, commit_id: str) -> dict[str, Any] | None: ...
    async def list_commits(self, ctx: Any, *, limit: int = 50) -> list[dict[str, Any]]: ...
    async def revert_commit(self, ctx: Any, commit_id: str, *, agent_id: str, run_id: str | None = None) -> Any: ...
    async def close(self) -> None: ...                 # no-op on sqlite/arangodb; pool close on postgres (:256)

@runtime_checkable
class IncrementalPersistence(Protocol):                 # sqlite :464, postgres :645
    async def is_stale(self, ctx: Any, source_uri: str, mtime: float, sha1: str) -> bool: ...

@runtime_checkable
class TemporalGraphPersistence(Protocol):               # postgres :1175, :1228, :1254
    async def as_of(self, ctx: Any, when: Any) -> tuple[list[Any], list[Any]]: ...
    async def history(self, ctx: Any, concept_id: str) -> list[Any]: ...
    async def diff(self, ctx: Any, concept_id: str, t1: Any, t2: Any) -> Any: ...

@runtime_checkable
class EmbeddingPersistence(Protocol):                   # postgres :1331 (S8: durable vectors live here, not in the embedder)
    async def upsert_embeddings(self, ctx: Any, vectors: dict[str, Any], *, model: str = "") -> int: ...

@runtime_checkable
class HybridRetrievalPersistence(Protocol):             # postgres :1484
    async def hybrid_retrieve(self, ctx: Any, query: str, *, top_k: int = 10, **options: Any) -> list[Any]: ...


# parrot/knowledge/graphindex/backends.py  (NEW — the only composition root, S3)
GraphBackendFactory = Callable[..., Awaitable[GraphPersistence]]

class GraphBackendSpec(BaseModel):
    """Registry entry: lazy module path, required options, declared capabilities."""
    name: str
    factory: str                      # "module:callable" — imported on first use
    required_options: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()  # "incremental" | "temporal" | "embeddings" | "hybrid"
    extra: str | None = None          # pip extra named in the ImportError message

def register_graph_backend(spec: GraphBackendSpec) -> None:
    """Register or replace a backend. Built-ins: sqlite, null, postgres, arangodb."""

def graph_backend_names() -> tuple[str, ...]: ...
def graph_backend_spec(name: str) -> GraphBackendSpec:
    """Raises ``ValueError`` naming the known backends for an unknown name."""

async def create_graph_persistence(backend: str, **options: Any) -> GraphPersistence:
    """Resolve ``backend`` through the registry and build it.

    sqlite: ``db_dir``. null: no options. postgres: ``dsn`` (explicit or resolved via
    ``resolve_setting("GRAPHINDEX_PG_DSN")``), ``schema="graphindex"``. arangodb:
    ``graph_store: GraphDocumentStore`` already connected, or ``arango_params`` +
    ``tenant_ctx`` (the factory connects and calls ``initialize_tenant``).
    Raises ``ValueError`` for an unknown backend or a missing required option
    (named), and the ``lazy_import`` ImportError naming the extra when a driver is absent.
    """


# parrot/knowledge/ontology/contracts.py  (NEW — M8)
class GraphDocumentStore(ABC):
    """Collection / document / edge CRUD — the surface GraphIndex's Arango persistence needs (S6).

    Method set lifted verbatim from graph_store.py: initialize_tenant (:91), ensure_collection
    (:570), upsert_nodes (:311), create_edges (:411), get_all_nodes (:488), soft_delete_nodes
    (:517), get_document (:598), upsert_document (:622), insert_document (:650),
    remove_document (:669), query_documents (:697), get_all_edges (:738), edges_incident
    (:764), remove_edge_by_triple (:791). Signatures unchanged.
    """

class OntologyTraversalStore(ABC):
    """Backend-neutral traversal surface for ontology callers (S5)."""
    dialect: ClassVar[str]                                # "aql" for ArangoDB

    async def is_reachable(self, ctx: TenantContext, start_id: str, target_id: str, *,
                           edge_collection: str, max_depth: int, direction: str = "outbound") -> bool:
        """authorization.py:247-262 (management chain) without composing AQL."""
    async def get_document_by_id(self, ctx: TenantContext, doc_id: str) -> dict[str, Any] | None:
        """authorization.py:334-345 (``RETURN DOCUMENT(@id)``)."""
    async def find_by_field(self, ctx: TenantContext, collection: str, field: str, value: Any, *,
                            filters: Mapping[str, Any] | None = None, limit: int = 2) -> list[dict[str, Any]]:
        """entity_resolver.py:370-386 exact match; ``filters`` are ANDed equalities (the former scope filter)."""
    async def search_by_name(self, ctx: TenantContext, collection: str, needle: str, *, field: str = "name",
                             filters: Mapping[str, Any] | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """entity_resolver.py:413-429 — case-insensitive contains, shortest name first."""
    async def execute_pattern(self, ctx: TenantContext, pattern: TraversalPattern, params: Mapping[str, Any],
                              collection_binds: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        """Run the template declared for ``self.dialect``; raises ``TraversalPatternUnavailable`` otherwise."""
    async def execute_query(self, ctx: TenantContext, query: DynamicQuery) -> list[dict[str, Any]]:
        """Dialect-bound escape hatch. Raises ``QueryDialectMismatch`` when ``query.dialect != self.dialect``.
        The only place raw query text crosses the contract; every call site states the dialect."""

def register_ontology_backend(name: str, factory: Callable[..., GraphDocumentStore]) -> None: ...
def create_ontology_graph_store(backend: str, **options: Any) -> GraphDocumentStore: ...   # "arangodb" built in

# parrot/knowledge/ontology/validators.py  (MODIFIED)
def register_query_validator(dialect: str, validator: Callable[[str, int | None], Awaitable[str]]) -> None: ...
async def validate_query(dialect: str, text: str, max_depth: int | None = None) -> str:
    """Dispatch to the registered validator; ``QueryValidationError`` (new base of
    ``AQLValidationError``) when none is registered — dynamic generation fails closed."""

# parrot/knowledge/ontology/exceptions.py  (MODIFIED — additive)
class QueryValidationError(OntologyError): ...
class AQLValidationError(QueryValidationError): ...     # was OntologyError (exceptions.py:27)
class QueryDialectMismatch(OntologyError): ...
class TraversalPatternUnavailable(OntologyError): ...


# parrot/knowledge/wiki/project.py  (NEW function — M4)
def resolve_setting(key: str, *, default: Any = None, explicit: Any = None,
                    project_defaults: Mapping[str, Any] | None = None) -> Any:
    """explicit → os.environ → optional navconfig → project_defaults → default.

    ``None`` means absent (``False``/``0``/``""`` are preserved). Environment membership is
    checked before navconfig is imported; a broken navconfig logs at debug and falls through.
    ``project_defaults`` is supplied by the caller from the effective config — this function
    never reads ``wiki.json``. Secrets are never echoed in errors or logs.
    """

# parrot/knowledge/wiki/store.py  (MODIFIED — M7)
def wiki_backend_names() -> tuple[str, ...]: ...        # built-ins + register_wiki_backend()
def resolve_wiki_backend(name: str) -> Callable[..., BaseWikiStore]: ...   # one dispatch for create_wiki_store + federation

# parrot/knowledge/wiki/sources_backend.py  (NEW — M7, S10)
class SourceManifestBackend(Protocol):
    """The eleven operations sources.py:1366-1425 + :306-927 perform per backend."""
    async def upsert(self, entry: SourceManifestEntry) -> None: ...
    async def upsert_many(self, entries: list[SourceManifestEntry]) -> None: ...
    async def list_sources(self) -> list[SourceManifestEntry]: ...
    async def get_source(self, source_id: str) -> SourceManifestEntry | None: ...
    async def remove_source(self, source_id: str) -> bool: ...
    async def find_id_by_uri(self, source_uri: str) -> str | None: ...
    async def find_by_external_id(self, external_id: str) -> SourceManifestEntry | None: ...
    async def find_by_uris(self, uris: list[str]) -> dict[str, SourceManifestEntry]: ...
    async def find_by_ids(self, source_ids: list[str]) -> dict[str, SourceManifestEntry]: ...
    async def find_by_external_ids(self, external_ids: list[str]) -> dict[str, SourceManifestEntry]: ...
    async def list_by_external_prefix(self, prefix: str) -> list[SourceManifestEntry]: ...
def register_source_backend(name: str, factory: Callable[..., SourceManifestBackend]) -> None: ...
def create_source_backend(name: str, **options: Any) -> SourceManifestBackend: ...   # sqlite · json · arangodb

# parrot/knowledge/wiki/transport.py  (NEW — M5, S11)
class OperationDescriptor(BaseModel):
    """Transport-neutral tool: name, description, input model, async invoke, result/error serializer, condition."""
    name: str
    description: str
    input_model: type[BaseModel]
    schema_fingerprint: str          # sha256 of the canonical JSON schema — golden-file comparable
    mount: str                       # "core" | "structural" | "decisions" | "schema" | "ledger" | "bulk" | "vault" | "remote"
def build_operation_descriptors(bundle_inputs: Any) -> list[OperationDescriptor]:
    """Deterministic; raises on duplicate names."""

# parrot/knowledge/wiki/mcp_server.py  (MODIFIED — M5)
def create_wiki_mcp_server(root: Path, *, transport: Literal["auto", "framework", "sdk"] = "auto") -> Any: ...
def create_proxy_mcp_server(remote: Any, *, transport: Literal["auto", "framework", "sdk"] = "auto") -> Any: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1 Lazy roots + harness | yes | PEP 562 `__getattr__` + `__all__` + `__dir__`; subprocess probe fixture; forbidden-prefix list in §1 | — |
| M2 Provider Protocols + adapters | yes | Protocol surfaces fixed in §2; adapter path `parrot/embeddings/graphindex.py`; `ProviderNotAvailable(role, distribution, extra)`; resolution order fixed | — |
| M3 Plain operations + relocation | yes | file layout §3; `_scoped_store`/`_unknown_namespace_error` stay in `wiki/operations.py`; wrapper classes move verbatim | — |
| M4 `resolve_setting` + pg_schema + SQL map | yes | signature + precedence fixed in §2; `parrot/knowledge/common/sql_dialects.py` | — |
| M5 MCP descriptors + transport | no | descriptor model fixed, but the SDK handler mapping (ToolResult ↔ MCP content, error envelopes) and the golden-manifest matrix need the thinking model | result/error serialization parity is a design judgment |
| M6 Document shapes + loader relocation | yes | `GraphDocument`, `DocumentLoader`, `parrot/loaders/graphindex.py`, lazy old-path export | — |
| M7 Graph persistence contract + registry | yes | Protocols, semantics, `GraphBackendSpec`, `create_graph_persistence` options, rename `ArangoPersistence`, dispatch sites, wiki registry, `SourceManifestBackend` all fixed in §2 | — |
| M8 Ontology contracts + typed traversals | partly | contracts, typed-op signatures and the AQL bodies (verbatim from the current call sites) are fixed; `parrot_tools` migrations mechanical | the intent-resolver prompt for a non-AQL dialect and the fail-closed policy wording stay with the thinking model |
| M9 Integration gate + FEAT-541 handoff | no | — | judgment over the residual-import inventory |

### Module 1: Lazy package roots + import-ceiling harness
- **Path**: `parrot/auth/__init__.py`, `parrot/knowledge/ontology/__init__.py`,
  `parrot/stores/__init__.py`, `parrot/knowledge/graphindex/__init__.py`,
  `packages/ai-parrot/tests/knowledge/test_import_ceilings.py` (new),
  `packages/ai-parrot/tests/knowledge/_support/import_probe.py` (new)
- **Responsibility**: PEP 562 roots for the three eager packages (land `auth`
  first — it is more than half of every excess) and for `graphindex/__init__.py`
  (its eager `communities`/`export_html`/`signals`/`persist_sqlite`/`projection`/
  `sqlite_reader`/`odoo_code` imports join `_LAZY_ATTRS`, `__init__.py:118-130`).
  Preserve every public name, `extend_path` (`stores/__init__.py:3`) and
  `supported_stores` (`:8`, including `lancedb`). The harness runs each import
  in a fresh subprocess with a fixed probe order, asserts the import
  *succeeded* before counting, records interpreter, revision and loaded
  forbidden prefixes (root and dotted), and reuses the existing
  `tests/test_minimal_install.py` blocked-package pattern (S12).
  `wiki/documents.py` already imports `aiohttp` lazily (`documents.py:583`);
  M1 adds only a regression test for that deferral.
- **Depends on**: nothing — it is the gate every other module is measured against.
- **Interface Skeleton**:
  ```python
  # parrot/auth/__init__.py  (modifies parrot/auth/__init__.py:29-48)
  __all__: list[str]            # every name exported today, unchanged
  _LAZY_ATTRS: dict[str, str]   # name -> submodule, e.g. "setup_pbac": "parrot.auth.pbac"
  def __getattr__(name: str) -> Any: ...   # PEP 562, cached in globals()
  def __dir__() -> list[str]: ...

  # packages/ai-parrot/tests/knowledge/_support/import_probe.py  (new)
  class ImportProbeResult(BaseModel):
      module: str; count: int; loaded_forbidden: list[str]; python: str; revision: str; error: str | None
  def run_import_probe(module: str, *, forbidden: tuple[str, ...]) -> ImportProbeResult:
      """Fresh ``sys.executable -I`` subprocess; counts len(sys.modules) after a successful import."""
  ```

### Module 2: Provider Protocols + framework adapters
- **Path**: `parrot/knowledge/graphindex/protocols.py` (new — providers part),
  `parrot/embeddings/graphindex.py` (new — the relocated `GraphIndexEmbedder`),
  `graphindex/embed.py` (becomes a lazy compatibility re-export),
  `builder.py`, `factory.py`, `retriever.py`, `signals.py`, `extractors/loader.py`
  (annotations), `wiki/triage.py`, `wiki/runtime.py`, `wiki/llm_resolve.py`,
  `wiki/inbox/{classify,links,processor}.py`
- **Responsibility**: declare `Embedder` / `LLMCaller` / `PageIndexer` /
  `ProviderNotAvailable` (§2); retype every consumer; move `GraphIndexEmbedder`
  out of the graph tree keeping its public behaviour (FAISS logging quieted
  only when the adapter is imported); **delete** `pgvector_dsn` and the stub
  `_persist_to_pgvector` (`embed.py:193`) — durable vectors are written by the
  backend's `EmbeddingPersistence` capability when present, coordinated by the
  builder (S8). The concrete FAISS wiring in `build_graph_memory_toolkit`
  (`factory.py:285-287`) moves to a framework helper
  `parrot/embeddings/graphindex.py:attach_hot_index(toolkit, embedder)`.
  Framework classes satisfy the Protocols structurally — never by inheritance.
  `OntologyIntentResolver` keeps calling `AbstractClient.completion`
  (`intent.py:176`): it is framework-side and not an import gateway (S7).
- **Depends on**: M1 (the ceiling test proves the severing).
- **Interface Skeleton**:
  ```python
  # parrot/embeddings/graphindex.py  (new; class body moved from graphindex/embed.py:25-206)
  class GraphIndexEmbedder:                               # satisfies Embedder structurally
      def __init__(self, model_name: str = ..., dimension: int = 384) -> None: ...   # pgvector_dsn removed
      async def embed_nodes(self, nodes: list[UniversalNode], batch_size: int = 64) -> list[UniversalNode]: ...
      def get_embedding(self, node_id: str) -> np.ndarray | None: ...               # embed.py:160
      async def search_similar(self, query_text: str, /, top_k: int = 10) -> list[tuple[str, float]]: ...  # embed.py:122
      def vectors(self) -> dict[str, np.ndarray]: """Hot vectors for EmbeddingPersistence.upsert_embeddings."""
  def attach_hot_index(toolkit: Any, embedder: GraphIndexEmbedder) -> None: ...   # factory.py:285-287 wiring

  # parrot/knowledge/graphindex/embed.py  (becomes a PEP 562 lazy re-export of the adapter)
  def __getattr__(name: str) -> Any: ...   # "GraphIndexEmbedder" -> parrot.embeddings.graphindex

  # parrot/knowledge/graphindex/builder.py  (modifies builder.py:116-136)
  class GraphIndexBuilder:
      def __init__(self, persistence: GraphPersistence, embedder: Embedder, ...,
                   pageindex_toolkit: PageIndexer | None = None, ...) -> None: ...
  ```

### Module 3: Plain wiki operations + relocation of every wrapper
- **Path**: `parrot/knowledge/wiki/operations.py` (new — core ops + shared
  helpers), `wiki/structural/operations.py`, `wiki/decisions/operations.py`,
  `wiki/schema/operations.py`, `wiki/ledger/operations.py` (new);
  `packages/ai-parrot-tools/src/parrot_tools/wiki/{__init__,tools,toolkit,
  structural,decisions,schema,ledger,bulk}.py` (new); the current
  `wiki/tools.py`, `wiki/toolkit.py`, `structural/{tools,toolkit}.py`,
  `decisions/{tools,toolkit}.py`, `schema/{tools,toolkit}.py` become lazy
  compatibility modules; `parrot_tools/business_automation/memory.py:31,110`;
  tests listed in §4.
- **Responsibility**: extract the framework-free operation functions and keep
  the Pydantic input models, `_scoped_store` (`tools.py:32`),
  `_unknown_namespace_error` (`:147`), `_reject_foreign_id` (`:58`),
  `_reject_managed_page` (`:88`), `_qualify_ledger_target` (`:123`), actor
  context, locking, ledger ownership checks, error conversion and output
  budgeting on the shared side. Move **all** `AbstractTool`/`AbstractToolkit`
  subclasses — core (`tools.py:230-665`), ledger (`:829-929`), bulk/sync
  (`:1003-1153`), `LLMWikiToolkit` (`toolkit.py:43`), structural
  (`structural/tools.py:106-181`, `toolkit.py:26`), decisions
  (`decisions/tools.py:100-178`, `toolkit.py:24`), schema
  (`schema/tools.py:44-116`, `toolkit.py:11`) — to `parrot_tools.wiki`.
  Importing an old path must not load `AbstractTool`; requesting a legacy
  class from it may. Internal plain consumers never use the shims.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # parrot/knowledge/wiki/operations.py  (new; bodies lifted from tools.py execute() methods)
  async def op_query(store: BaseWikiStore, params: WikiQueryInput, *, namespace: str | None = None) -> OperationResult: ...
  async def op_page(...), op_related(...), op_remember(...), op_note(...), op_status(...), op_lint(...), op_standup(...)
  class OperationResult(BaseModel):
      """Transport-neutral result: text, structured payload, is_error — mapped to ToolResult or MCP content."""
      text: str; data: dict[str, Any] | None = None; is_error: bool = False
  # parrot_tools/wiki/tools.py  (new; classes moved verbatim from wiki/tools.py:230-1153)
  class WikiQueryTool(AbstractTool): ...   # execute() delegates to operations.op_query
  ```

### Module 4: `resolve_setting()`, Postgres configuration and the SQL dialect map
- **Path**: `wiki/project.py`, `wiki/cli.py:576`, `wiki/llm_resolve.py:11`,
  `graphindex/loader.py:337` (moves with M6), `graphindex/pg_schema.py:19-23`,
  `parrot/knowledge/common/sql_dialects.py` (new), `parrot/tools/sql_dialects.py:27`
  (re-export), `wiki/cli.py:46`, `wiki/schema/render.py:14`, `wiki/schema/producers/ddl.py:13`
- **Responsibility**: implement `resolve_setting()` (§2) and fold `_navconfig`
  (`project.py:792`), `_env_credential` (`:822`), `_env_setting` (`cli.py:576`,
  `llm_resolve.py:11`) into it; `resolve_arango_params` (`:851`),
  `resolve_wiki_env` (`:1112`), effective-config overlays and SQLite policy keep
  their signatures and semantics. Remove the eager `navconfig`/`parrot.conf`
  imports from `pg_schema.py`; connection settings resolve when the Postgres
  backend is selected (M7 factory); framework wiring may pass its default DSN
  explicitly; standalone requires an explicit/configured DSN and fails before
  network I/O naming the missing keys. The implicit Arango loopback default
  goes away (a loopback the user configured stays valid) — covered by tests.
  Move `_SQLGLOT_DIALECT_MAP` to the neutral module; repoint CLI, render and
  DDL producers; the tools module re-exports.
- **Depends on**: M1.
- **Interface Skeleton**: `resolve_setting` as in §2; `pg_schema.resolve_pg_settings(*, dsn=None, schema=None) -> PgSettings` (new, replaces the module-level constants resolved at import).

### Module 5: MCP transport descriptors + selector
- **Path**: `wiki/transport.py` (new), `wiki/mcp_server.py`, `wiki/serve.py`
  (verification only), `tests/knowledge/wiki/golden/mcp_manifests/*.json` (new)
- **Responsibility**: build `OperationDescriptor`s from the operation registry
  (M3) for every mount — core, structural, decisions, schema, ledger, bulk/sync,
  vault (gated on the Obsidian adapter, `mcp_server.py:303`), remote proxy —
  with duplicate-name validation and schema fingerprints (S11); adapt them to
  framework `AbstractTool`s (via `parrot_tools.wiki`) or to SDK stdio handlers.
  Add the keyword-only `transport` selector (`auto` prefers the framework
  transport and falls back only on *transport* unavailability; `framework`
  reports missing dependencies; `sdk` never probes the framework). Preserve
  `WikiToolBundle`, `abuild_wiki_tools`, `build_wiki_tools`, `close_bundle`
  (`mcp_server.py:93-352`) for `serve.py:156,196`. Capture golden manifests
  for: minimal local, ledger, decisions, schema present/absent, federated
  namespaces, bulk on/off, vault configured, remote proxy. Tool count is
  configuration-dependent — there is no fixed six-tool contract. Preserve
  actor propagation, write-target rules, structural `read_repair`, SQLite
  policy, clean JSON-RPC stdout and closure of owned stores on shutdown/error/
  cancellation. `mcp>=1.28.1,<2` is already a core extra (`pyproject.toml:436`).
- **Depends on**: M3.
- **Interface Skeleton**: `OperationDescriptor`, `build_operation_descriptors`, `create_wiki_mcp_server(..., transport=)`, `create_proxy_mcp_server(..., transport=)` as in §2; `wiki/transport.py: def to_framework_tools(descriptors) -> list[Any]` (imports `parrot_tools.wiki` lazily) and `def to_sdk_server(descriptors, *, name: str) -> Any` (imports `mcp` lazily).

### Module 6: `GraphDocument` / `DocumentLoader` shapes + loader relocation
- **Path**: `graphindex/models.py` (new), `graphindex/extractors/loader.py:38,42,198`,
  `parrot/loaders/graphindex.py` (new — `GraphIndexLoader` moved from
  `graphindex/loader.py:96-416`), `graphindex/loader.py` (lazy compatibility
  export), `graphindex/__init__.py` (`_LAZY_ATTRS["GraphIndexLoader"]`)
- **Responsibility**: define the shapes (§2); the extractors consume
  `DocumentLoader`/`GraphDocument`; the framework adapter converts
  `parrot.stores.models.Document` ↔ `GraphDocument` preserving `page_content`
  and `metadata` only. `GraphIndexLoader` keeps its constructor, `load()`
  behaviour and old import path (lazy); its persistence selection goes through
  `create_graph_persistence` (M7) and its navconfig block through
  `resolve_setting` (M4). The ebook helper import (`extractors/loader.py:198`)
  stays an explicitly lazy optional adapter seam inventoried for FEAT-541.
- **Depends on**: M2, M4, M7 (all three edit the old loader — sequence after them).
- **Interface Skeleton**: `GraphDocument`, `DocumentLoader` as in §2; `parrot/loaders/graphindex.py: class GraphIndexLoader(AbstractLoader)` (unchanged signature, `loader.py:130`); `def to_graph_document(doc: Document) -> GraphDocument` / `def from_graph_document(doc: GraphDocument) -> Document` in the same module.

### Module 7: GraphIndex persistence contract + backend registry *(new)*
- **Path**: `graphindex/protocols.py` (persistence part), `graphindex/backends.py`
  (new), `graphindex/persist.py` → `graphindex/persist_arango.py` (rename),
  `persist_sqlite.py` (add `close()`), `persist_postgres.py` (conformance only),
  `publish.py:47`, `builder.py:505`, `factory.py:249-261`, `wiki/runtime.py:91`,
  `wiki/cli.py:4011,4108,4561,4623`, `flows/dev_loop/graph_memory.py:142`,
  `graphindex/loader.py:288-313` (with M6), `parrot_tools/graphindex/toolkit.py:306,1326`,
  `parrot_tools/graphindex/flowtask.py:27,220`, `contracts/temporal.py:361-375`,
  `retrieval/pin.py:416`; wiki side: `wiki/store.py` (`wiki_backend_names`,
  `resolve_wiki_backend`, `_BUILTIN_BACKENDS`), `wiki/models.py:114`,
  `wiki/project.py:605,1063`, `wiki/sources.py:148,1303-1425`,
  `wiki/sources_backend.py` (new), `wiki/arango_sources.py` (new),
  `wiki/federation.py:418`, `wiki/toolkit.py:139-161`
- **Responsibility**: declare the base and capability Protocols with the
  semantics in §2 (S2) and ship a **conformance suite** every backend runs
  (apply/revert/seq monotonicity, slice atomicity + idempotence, missing-store
  reads empty, error propagation) against sqlite, null and fake adapters, with
  the live Postgres/Arango tiers reusing it under their existing `skipif`
  gates (S12). `backends.py` is the only composition root (S3): built-ins
  `sqlite`, `null` (the loader's `_NullPersistence`, `loader.py:44`, promoted
  and tested), `postgres` and `arangodb` registered with lazy factory paths,
  required options and capabilities; every dispatch site calls
  `create_graph_persistence`; `GraphPublisher` and `GraphIndexBuilder` are
  typed to `GraphPersistence`; capability use is `isinstance` (toolkit,
  temporal contracts) and raises `CapabilityUnavailable` with the backend
  name otherwise; `pin.py` guards `isinstance(persistence, SQLitePersistence)`
  and rejects other backends before opening anything (S9). `ArangoPersistence`
  takes a `GraphDocumentStore` (M8), never the typed traversal contract (S6).
  Wiki: the three `Literal`s and `SourceCollectionManager.backend` become
  `str` validated at open time by `wiki_backend_names()`; `create_wiki_store`
  and `federation.py:418` share `resolve_wiki_backend`; the eleven Arango
  source operations move verbatim into `ArangoSourceBackend`, `SQLite`/`JSON`
  implementations wrap the existing in-class code, and `SourceCollectionManager`
  holds one `SourceManifestBackend` instead of 25 `backend ==` branches
  (S10); `LLMWikiToolkit` selects through `create_source_backend`.
- **Depends on**: M1 (ceilings), M4 (`resolve_setting` for Postgres/Arango
  options). M8 for the `GraphDocumentStore` type (annotation only — may land
  behind `TYPE_CHECKING` first).
- **Interface Skeleton**: `GraphPersistence` + capabilities, `GraphBackendSpec`, `register_graph_backend`, `graph_backend_names`, `graph_backend_spec`, `create_graph_persistence`, `wiki_backend_names`, `resolve_wiki_backend`, `SourceManifestBackend`, `register_source_backend`, `create_source_backend` as in §2, plus:
  ```python
  # parrot/knowledge/graphindex/persist_arango.py  (renamed from persist.py; class renamed)
  class ArangoPersistence:                                   # satisfies GraphPersistence
      def __init__(self, store: GraphDocumentStore) -> None: ...   # was graph_store: OntologyGraphStore (persist.py:225)
      async def close(self) -> None: ...                     # no-op; the store owns the client
  # parrot/knowledge/graphindex/persist_sqlite.py  (modifies :138)
  class SQLitePersistence:
      async def close(self) -> None: ...                     # no-op (connections are per-call)
  # parrot/knowledge/graphindex/backends.py — built-in null backend (moved from loader.py:44-95)
  class NullPersistence: """In-memory no-op; satisfies GraphPersistence; load_graph() -> ([], [])."""
  ```

### Module 8: Ontology graph-store contracts + typed traversals *(new)*
- **Path**: `ontology/contracts.py` (new), `ontology/graph_store.py` (rename to
  `ArangoOntologyGraphStore`, implement both contracts, AQL private),
  `ontology/__init__.py` (export both names lazily), `ontology/schema.py:261-290,547-571`,
  `ontology/intent.py:42,150,212,220-226,275`, `ontology/validators.py:36`,
  `ontology/exceptions.py:27`, `ontology/authorization.py:39-58,257,339`,
  `ontology/entity_resolver.py:25,116-122,315-429`, `ontology/mixin.py:70,120,337-381`,
  `graphindex/persist_arango.py` (type), `parrot/loaders/graphindex.py` (constructs
  the Arango store through `create_ontology_graph_store`),
  `parrot_tools/legal/wiki_store.py:209,265-486`, `parrot_tools/legal/boe/sync.py:62`,
  `parrot_tools/legal/boe/queries.py:72,176`, `parrot_tools/procedures/retrieval.py:292,311`,
  `parrot_tools/contracts/retrieval.py:681,719`; tests listed in §4.
- **Responsibility**: implement §2's `GraphDocumentStore` and
  `OntologyTraversalStore`; `ArangoOntologyGraphStore` implements the typed
  operations with the AQL that the current call sites compose today, moved
  verbatim (management chain `authorization.py:247-251`, `DOCUMENT()` lookup
  `:334`, exact match `entity_resolver.py:370-375`, fuzzy match `:413-420`);
  `execute_traversal` is removed from the public surface. `TraversalPattern`
  gains `query_templates` (additive; existing ontology YAML keeps working).
  `ResolvedIntent.aql`/`IntentDecision.aql` → `query` + `dialect` (hard cut;
  the intent resolver takes the store's dialect and renders its prompt
  (`intent.py:275`) for that dialect); `validate_query(dialect, …)` dispatches
  to registered validators — AQL keeps today's regex validator; a dialect
  without a validator makes dynamic generation **fail closed** (`vector_only`
  degradation, logged), declared patterns are unaffected (S5). The mixin runs
  `execute_query(ctx, DynamicQuery(dialect=intent.dialect, text=intent.query,
  …))`; `execute_pattern` serves `boe/queries`, `procedures`, `contracts`
  (`aql_for` → `pattern_for` returning the `TraversalPattern`); `legal/
  wiki_store.py` and `boe/sync.py` construct `ArangoOntologyGraphStore`
  explicitly and call `execute_query(..., dialect="aql")` for their eight
  inline statements — explicitly Arango-bound by construction, no longer
  hidden behind a generic name. `search_views` (`schema.py:331,444`) are an
  Arango capability: a non-Arango store's `initialize_tenant` logs and skips
  them. `TenantContext.arango_db` is kept (§8 Q1).
- **Depends on**: M1 (lazy ontology root). M7 consumes its `GraphDocumentStore`.
- **Interface Skeleton**: as in §2 (`GraphDocumentStore`, `OntologyTraversalStore`, `DynamicQuery`, `register_ontology_backend`, `create_ontology_graph_store`, `validate_query`, `register_query_validator`, the three new exceptions), plus:
  ```python
  # parrot/knowledge/ontology/graph_store.py  (modifies graph_store.py:53-69)
  class ArangoOntologyGraphStore(GraphDocumentStore, OntologyTraversalStore):
      dialect: ClassVar[str] = "aql"
      def __init__(self, arango_client: Any = None) -> None: ...      # unchanged (graph_store.py:69)
      async def _execute_aql(self, ctx, aql, bind_vars=None, collection_binds=None) -> list[dict]: ...  # was execute_traversal (:271)
  # parrot/knowledge/ontology/intent.py  (modifies intent.py:42,79)
  class IntentDecision(BaseModel):
      query: str | None = None                                        # was aql
  class OntologyIntentResolver:
      def __init__(self, ontology: MergedOntology, llm_client: Any = None, *, dialect: str = "aql", ...) -> None: ...
  # parrot/knowledge/ontology/authorization.py  (modifies :53-58)
  class AuthorizationChecker:
      def __init__(self, graph_store: OntologyTraversalStore, ...) -> None: ...
  # parrot_tools/procedures/retrieval.py  (modifies :311)
  def pattern_for(self, pattern: str) -> TraversalPattern: ...        # was aql_for -> str
  ```

### Module 9: Integration gate + FEAT-541 handoff
- **Path**: `tests/knowledge/test_import_ceilings.py` (activate every ceiling),
  `tests/knowledge/test_graph_tree_imports.py` (AST scan + dynamic blocker),
  `tests/knowledge/wiki/test_cli_surface.py` (recursive command/option
  inventory), `docs/graphindex/core-seams.md` (new — seams, registries, how to
  plug a backend), `sdd/state/FEAT-540/handoff-541.md` (new — residual-import
  inventory with owner and behaviour-when-absent: Jira/Obsidian, ebooks, egress
  acquisition, coding-agent guard installers, framework toolkit factories,
  `pin.py` SQLite boundary, `legal` Arango-bound tools)
- **Responsibility**: turn every §5 criterion into a passing test or a recorded
  evidence file under `artifacts/logs/FEAT-540-*`; the AST scan inspects
  executable module-level branches and exempts only `TYPE_CHECKING`; the
  dynamic blocker runs the default entry points and plain operation paths with
  the forbidden packages blocked via `sys.meta_path`; compatibility: old public
  imports resolve lazily, existing SQLite planes reopen with identical
  deterministic fixture counts.
- **Depends on**: M1–M8.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_auth_root_lazy` | M1 | `parrot.auth.exceptions` imports without `.pbac`/`parrot.conf`; `from parrot.auth import setup_pbac, RlsRegistry` still resolve; `dir(parrot.auth)` lists them |
| `test_ontology_root_lazy` / `test_stores_root_lazy` / `test_graphindex_root_lazy` | M1 | names resolve; expensive submodules absent after importing only the cheap ones; `supported_stores` and `extend_path` unchanged |
| `test_documents_aiohttp_deferred` | M1 | importing `wiki.documents` leaves `aiohttp` out of `sys.modules` (regression for `documents.py:583`) |
| `test_protocols_structural_match` | M2 | `GraphIndexEmbedder`, `HashingGraphEmbedder`, `PageIndexLLMAdapter`, `PageIndexToolkit` satisfy their Protocols; a double missing `search_similar` does not |
| `test_builder_retriever_signals_with_typed_double` | M2 | builder, retriever and signals run against a typed `Embedder` double (not attribute-presence only) |
| `test_default_embedder_hashing_deterministic` | M2 | no provider → `HashingGraphEmbedder`; identical vectors across runs |
| `test_provider_not_available` | M2 | required provider absent → `ProviderNotAvailable(role, distribution, extra)`; CLI exit 2; optional-model paths (`resolve_optional_llm`) still degrade to `None` |
| `test_embedder_no_pgvector_stub` | M2 | `GraphIndexEmbedder` has no `pgvector_dsn`; builder calls `EmbeddingPersistence.upsert_embeddings` only when the backend declares it |
| `test_operations_shared_by_both_transports` | M3/M5 | each descriptor's invoke and the matching `parrot_tools.wiki` tool call the same operation function (spy) |
| `test_old_paths_lazy` | M3 | importing `parrot.knowledge.wiki.tools` does not load `parrot.tools.abstract`; `WikiQueryTool` attribute access does |
| `test_parrot_tools_wiki_exports` | M3 | all relocated toolkits/tools importable from `parrot_tools.wiki`; `business_automation.memory` repointed |
| `test_resolve_setting_precedence` / `_falsey` / `_navconfig_broken` / `_secret_safe` | M4 | explicit → env → navconfig → project defaults → default; `False`/`0`/`""` preserved; broken navconfig logs at debug; errors never echo values |
| `test_pg_schema_import_clean` / `test_pg_settings_missing_keys` | M4 | importing `pg_schema` loads no `asyncpg`/`navconfig`/`parrot.conf`; missing DSN fails before I/O naming the keys |
| `test_arango_no_implicit_loopback` | M4 | missing `ARANGODB_*` → actionable error, not `127.0.0.1`; explicit loopback accepted |
| `test_sql_dialect_map_relocated` | M4 | `parrot.knowledge.common.sql_dialects` and the tools re-export are the same object; render/DDL output identical |
| `test_descriptors_unique_and_fingerprinted` | M5 | duplicate name raises; fingerprints stable across runs |
| `test_mcp_manifest_golden[config]` | M5 | per configuration in M5's matrix: names, canonical schemas, descriptions, mount conditions byte-equal to the golden file for both transports |
| `test_transport_selector` | M5 | `sdk` with `parrot.mcp`/`parrot.tools`/`parrot_tools` blocked works; `framework` reports the missing dependency; `auto` falls back only on transport unavailability |
| `test_bundle_lifecycle` | M5 | `abuild_wiki_tools`/`close_bundle` close owned stores on shutdown, error and cancellation; stdout stays clean JSON-RPC |
| `test_graph_document_roundtrip` / `test_extractor_with_plain_loader` | M6 | content/metadata preserved; extractors run on a `DocumentLoader` double |
| `test_graphindex_loader_relocated` | M6 | old import path resolves lazily; constructor and `load()` unchanged |
| `test_persistence_conformance[backend]` | M7 | shared suite: apply/revert, monotonic `seq`, slice atomicity + idempotence, missing store reads empty, error propagation — for `sqlite`, `null`, a fake adapter; live `postgres`/`arangodb` under their `skipif` gates |
| `test_registry_dispatch` | M7 | unknown backend → `ValueError` listing names; missing option named; missing driver → `lazy_import` message with the extra; factories imported lazily |
| `test_no_hasattr_capability_probes` | M7 | toolkit/temporal paths use `isinstance`; unsupported backend → `CapabilityUnavailable(backend)` |
| `test_pin_sqlite_only_boundary` | M7 | `check_pin_coherence` rejects a non-SQLite backend before opening anything |
| `test_wiki_backend_registry_validation` | M7 | `backend="helixdb"` unregistered → validation error at open naming known backends; registered satellite name accepted in `WikiConfig`, `WikiProjectConfig`, `WikiEnvOverlay`, `SourceCollectionManager` |
| `test_source_backend_parity[sqlite,json,arangodb-fake]` | M7 | the eleven operations behave identically; `SourceCollectionManager` has no `backend ==` branch left (AST assertion) |
| `test_typed_traversals_arango_aql_verbatim` | M8 | each typed op issues exactly the AQL text and binds the current call sites issue (captured from `dev`) |
| `test_authorization_entity_resolver_typed` | M8 | `AuthorizationChecker`/`EntityResolver` run on an `OntologyTraversalStore` fake with no AQL in core |
| `test_execute_pattern_dialect` | M8 | `query_templates[dialect]` wins; `query_template` serves `aql`; missing → `TraversalPatternUnavailable` |
| `test_execute_query_dialect_mismatch` | M8 | `DynamicQuery(dialect="cypher")` on the Arango store → `QueryDialectMismatch` |
| `test_dynamic_query_fail_closed` | M8 | unregistered dialect → `QueryValidationError`, resolver degrades to `vector_only`; AQL validator behaviour unchanged (existing `test_ontology_validators.py`) |
| `test_intent_models_hard_cut` | M8 | `ResolvedIntent.query`/`.dialect`, `IntentDecision.query`; prompt names the dialect |
| `test_parrot_tools_pattern_callers` | M8 | `boe/queries`, `procedures`, `contracts` call `execute_pattern`; `legal/wiki_store` calls `execute_query(dialect="aql")` on an explicitly Arango store |
| `test_arango_persistence_over_document_store` | M8/M7 | `ArangoPersistence` runs the commit protocol against a `GraphDocumentStore` fake |

### Integration Tests

| Test | Description |
|---|---|
| `test_import_ceilings[entry_point]` | subprocess probe per §1 row — successful import, count ≤ ceiling, no forbidden prefix (root or dotted); evidence JSON written to `artifacts/logs/` |
| `test_graph_tree_no_framework_imports` | AST scan of `wiki/**` + `graphindex/**` + `ontology/{contracts,schema,validators}.py`: no module-level or executable-branch import of the G2 list; only `TYPE_CHECKING` exempt |
| `test_dynamic_import_blocker` | default CLI entry points and plain operations run with the forbidden packages blocked in `sys.meta_path`; lazy adapters tested separately, never whole-module exclusions |
| `test_wikitoolkit_build_end_to_end` | fixture repo → identical page/edge/symbol counts to the pre-change baseline on SQLite |
| `test_existing_planes_reopen` | pre-FEAT-540 `wiki.db` / `<tenant>.db` fixtures open and query unchanged |
| `test_cli_surface_inventory` | recursive command/option inventory (incl. remote/serve, ledger, decisions, schema, inbox, standup) equals the captured baseline |
| `test_agent_path_unchanged` | agent wired with `parrot_tools.wiki.LLMWikiToolkit` + `GraphIndexToolkit` on `backend="sqlite"` answers a query with a real embedder adapter and a stub LLM |
| `test_mcp_sdk_local_and_proxy_smoke` | SDK transport, framework modules blocked: tools/list + tools/call round-trip locally and through the proxy |

### Test Data / Fixtures

```python
@pytest.fixture
def import_probe():
    """Run one import in a fresh ``python -I`` subprocess; returns ImportProbeResult (M1)."""

@pytest.fixture
def fake_graph_persistence():
    """In-memory GraphPersistence + IncrementalPersistence double used by the conformance suite and the toolkit tests."""

@pytest.fixture
def fake_traversal_store():
    """OntologyTraversalStore double recording typed calls; dialect="fake"; no validator registered."""

@pytest.fixture
def captured_aql():
    """Dict of the AQL strings + bind shapes issued on dev @ 246f1bb6d by authorization/entity_resolver (golden)."""
```

---

## 5. Acceptance Criteria

- [ ] All five §1 ceilings pass in fresh subprocesses; none of the forbidden
      prefixes (root or dotted) is loaded; evidence under `artifacts/logs/`.
- [ ] AST scan + dynamic import blocker pass for the graph tree (G2), with only
      `TYPE_CHECKING` exemptions.
- [ ] `Embedder`/`LLMCaller`/`PageIndexer` doubles exercise embedding, similarity
      lookup, retrieval, PageIndex extraction and LLM consumers; concrete classes
      satisfy the Protocols; hashing default deterministic; required-provider
      errors exit 2; optional-model paths still degrade safely.
- [ ] `GraphIndexEmbedder` lives under `parrot/embeddings/`, old path lazy, no
      pgvector stub; durable vectors go through `EmbeddingPersistence`.
- [ ] Every wiki tool family preserves canonical schemas, names, descriptions and
      observable results/errors across framework and SDK transports for the full
      M5 configuration matrix (golden manifests).
- [ ] SDK local/proxy smoke tests pass with `parrot.mcp`, `parrot.tools`,
      `parrot_tools` blocked; framework stdio and HTTP `serve.py` lifecycle tests
      pass, including cleanup and clean stdout.
- [ ] Recursive CLI inventory unchanged.
- [ ] `resolve_setting()` is the only configuration reader in the graph tree
      (explicit `os.environ` reads for subprocess env, actor identity and feature
      switches excepted); precedence, falsey, broken-navconfig, overlays, explicit
      DB configuration and secret-safe failures covered; no implicit Arango loopback.
- [ ] `pg_schema.py` imports clean; Postgres settings resolve at selection.
- [ ] SQL dialect map relocated with identical render/DDL output.
- [ ] `graph_backend_names() == ("sqlite", "null", "postgres", "arangodb")`;
      every dispatch site listed in M7 calls `create_graph_persistence`; a
      `grep` for `SQLitePersistence(` outside `backends.py`, `persist_sqlite.py`,
      `pin.py` and tests returns nothing.
- [ ] Conformance suite passes for `sqlite`, `null` and the fake adapter; live
      Postgres/Arango tiers pass or are reported as *unavailable*, never as passing.
- [ ] No `hasattr(persistence, …)` capability probe remains in `parrot_tools/graphindex`
      or `knowledge/contracts`; unsupported capabilities raise `CapabilityUnavailable`.
- [ ] Wiki backend names validate against the registry in all four former
      `Literal` sites; `parrot_tools.legal`'s `ontology_legal` registration keeps working.
- [ ] `SourceCollectionManager` delegates to a `SourceManifestBackend`; parity
      across sqlite/json/arangodb-fake; no `backend ==` branch left.
- [ ] `execute_traversal` no longer exists; core ontology code contains no AQL
      text (grep for `FOR ` / `RETURN ` in `authorization.py`, `entity_resolver.py`,
      `mixin.py` returns nothing); typed operations issue the captured AQL verbatim.
- [ ] `ResolvedIntent.query/dialect`, `TraversalPattern.query_templates`,
      `validate_query` dispatch and fail-closed dynamic generation covered;
      existing AQL validator tests pass unchanged.
- [ ] `parrot_tools` legal/procedures/contracts callers migrated; their existing
      suites pass.
- [ ] Old public imports (`graphindex.persist`'s callers updated — no shim;
      `graphindex.embed`, `graphindex.loader`, `wiki.tools`, `wiki.toolkit`,
      `structural/decisions/schema tools+toolkits`, `ontology.OntologyGraphStore`
      → **removed**, callers updated) behave as stated in §7; no eager shim
      reintroduces the import cost.
- [ ] Existing SQLite wiki and graph planes reopen and query unchanged;
      deterministic fixture counts match the baseline.
- [ ] Focused suites pass: `tests/knowledge/`, `tests/test_minimal_install.py`,
      auth/PBAC consumers, loaders, MCP/server, `packages/ai-parrot-tools/tests/
      {graphindex,legal,procedures,contracts,business_automation}`; then
      `pytest packages/ai-parrot/tests/knowledge/ -v` and
      `pytest packages/ai-parrot-tools/tests/ -v`.
- [ ] `ruff check` and Black (120) clean on changed files; type hints and
      Google-style docstrings on every new/changed public symbol; test logs under
      `artifacts/logs/`, unavailable live tiers distinguished from passes.
- [ ] `docs/graphindex/core-seams.md` documents the four seams and "how to plug
      a graph backend" (the recipe FEAT-670 follows); `sdd/state/FEAT-540/handoff-541.md`
      inventories every residual function-local optional framework import.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every entry re-verified on
> **2026-10-14** against `dev` @ `246f1bb6d` (`packages/` identical to
> `origin/dev` @ `048479633`). The v0.3 (Codex) findings are carried where
> re-verified; v0.1/v0.2 line numbers are superseded.

### Verified Imports

```python
from parrot.knowledge.ontology.schema import TenantContext, MergedOntology, TraversalPattern, ResolvedIntent  # schema.py:529, 452, 261, 547
from parrot.knowledge.ontology.graph_store import OntologyGraphStore           # graph_store.py:53  (renamed by M8)
from parrot.knowledge.ontology.validators import validate_aql                  # validators.py:36
from parrot.knowledge.ontology.exceptions import AQLValidationError, OntologyError  # exceptions.py:27, 4
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence       # persist_sqlite.py:138
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence   # persist_postgres.py:207
from parrot.knowledge.graphindex.persist import GraphIndexPersistence          # persist.py:213  (renamed by M7)
from parrot.knowledge.graphindex.publish import GraphPublisher                 # publish.py:37
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit, make_stub_tenant_context, HashingGraphEmbedder, DEFAULT_DIMENSION  # factory.py:197, 45, 116, 42
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder               # embed.py:25
from parrot.knowledge.graphindex.builder import GraphIndexBuilder              # builder.py:60
from parrot.knowledge.graphindex.schema import UniversalNode, UniversalEdge, GraphUpdate, CommitReceipt, AssertionMeta
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore, register_wiki_backend, create_wiki_store, WikiPageRecord  # store.py:553, 948, 539, 2665, 433
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiNamespaceConfig, WikiEnvOverlay, _navconfig, _env_credential, resolve_arango_params, resolve_wiki_env, sqlite_policy_from_config  # project.py:561, 186, 1026, 792, 822, 851, 1112, 928
from parrot.knowledge.wiki.models import WikiConfig                            # models.py (storage_backend at :114)
from parrot.knowledge.wiki.sources import SourceCollectionManager              # sources.py:144 (__init__)
from parrot.knowledge.wiki.llm_resolve import resolve_optional_llm, _env_setting  # llm_resolve.py:31, 11
from parrot.knowledge.wiki.tools import create_wiki_tools, create_bulk_tools   # tools.py:1221, 1211
from parrot.knowledge.wiki.mcp_server import WikiToolBundle, abuild_wiki_tools, build_wiki_tools, close_bundle, create_wiki_mcp_server, create_proxy_mcp_server, main  # mcp_server.py:93, 105, 321, 352, 373, 408, 465
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter         # llm_adapter.py:42
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit                # toolkit.py:54
from parrot.embeddings.registry import EmbeddingRegistry                       # registry.py:55
from parrot.utils.faiss_logging import quiet_faiss_loader                      # faiss_logging.py:34
from parrot.stores.models import Document                                      # models.py:19
from parrot.loaders.abstract import AbstractLoader                             # abstract.py:100
from parrot.mcp.local_server import StdioMCPServer                             # local_server.py:54
from parrot.tools.sql_dialects import _SQLGLOT_DIALECT_MAP                     # sql_dialects.py:27
from parrot._imports import lazy_import                                        # _imports.py:110
from parrot_tools.graphindex.toolkit import GraphIndexToolkit                  # toolkit.py:110
```

### Existing Class Signatures

```python
# ── package roots ──
# parrot/auth/__init__.py:29-48 — eager: .context, .permission, .resolver, .pbac(:38), .eval_context, .userinfo, .dataset_guard, .dataplane_guard, .rls_registry, .models
#   pbac.py:30  from parrot.conf import PARROT_SAAS_MODE
# parrot/knowledge/ontology/__init__.py:2-7 — eager: cache, graph_store, intent, mixin(:5), schema, tenant; __all__ :9-19
# parrot/stores/__init__.py — :1 extend_path import, :3 __path__ = extend_path(...), :5 from .abstract import AbstractStore, :8 supported_stores = {...}
#   stores/abstract.py:7  from navconfig.logging import logging
# parrot/knowledge/graphindex/__init__.py — eager imports :16-61 (schema, signals, communities, export_html, persist_sqlite(:53), projection, sqlite_reader, odoo_code(:61)); __all__ :63-111; _LAZY_ATTRS :118-130; __getattr__ :133

# ── providers ──
# graphindex/embed.py
from parrot.embeddings.registry import EmbeddingRegistry        # :15
from parrot.utils.faiss_logging import quiet_faiss_loader       # :17
quiet_faiss_loader()                                            # :19
import faiss                                                    # :20
class GraphIndexEmbedder:                                       # :25
    async def search_similar(...)                               # :122
    def get_embedding(self, node_id: str) -> Optional[np.ndarray]  # :160
    async def _persist_to_pgvector(self, node_id, embedding) -> None  # :193  ← STUB ("logs on failure")
# graphindex/builder.py
from parrot.knowledge.graphindex.embed import GraphIndexEmbedder            # :34
from parrot.knowledge.graphindex.persist import GraphIndexPersistence       # :43
from parrot.knowledge.ontology.schema import TenantContext                  # :54
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit             # :55  ← sever
class GraphIndexBuilder:                                                    # :60
    def __init__(self, persistence: GraphIndexPersistence, embedder: GraphIndexEmbedder, ..., pageindex_toolkit: PageIndexToolkit | None = None, ...)  # :116-123
    if hasattr(self.persistence, "is_stale"):                               # :505
# graphindex/factory.py
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence    # :33
DEFAULT_DIMENSION = 256                                                     # :42
def make_stub_tenant_context(tenant_id: str) -> TenantContext               # :45
class HashingGraphEmbedder:                                                 # :116  (_node_id_map :139)
async def build_graph_memory_toolkit(db_dir=None, tenant_id="default", agent_id="agent", run_id=None, embedder=None, client=None, dimension=DEFAULT_DIMENSION, backend: str = "sqlite", dsn=None, schema="graphindex")  # :197-208
    if backend == "sqlite": ... elif backend == "postgres": ... else: raise ValueError  # :249-261
    faiss_index=embedder.index, node_id_list=list(embedder._node_id_map)    # :285-287
# graphindex/retriever.py:321   raw = await self.embedder.search_similar(
# graphindex/signals.py:395,466,528,557   embedder: Optional["GraphIndexEmbedder"]; :404-405 embedder.get_embedding(...)
# wiki/triage.py:42 from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter; class NoveltyScorer :67 (grounding_evaluator kwarg :90); class IngestTriageRouter :243
# wiki/llm_resolve.py: def _env_setting(name) :11; def resolve_optional_llm(env_names, *, purpose, logger) -> "PageIndexLLMAdapter | None" :31 (lazy LLMFactory + adapter imports)
# wiki/runtime.py: adapters built :41-49; SQLitePersistence import :82, instantiation :91; PageIndexToolkit :144,162
# wiki/inbox/classify.py:9,117 · links.py:6,36 · processor.py:15,58-59 — PageIndexLLMAdapter annotations
# pageindex/llm_adapter.py: class PageIndexLLMAdapter :42; ask :61; ask_structured :99; ask_with_finish_info :151; ask_json :201
# pageindex/toolkit.py: class PageIndexToolkit(AbstractToolkit) :54; __init__ :92; list_trees :404; create_tree :408; delete_tree :430; get_tree :550; insert_markdown :819; insert_ebook :857
# ontology/intent.py:176   response = await self.llm.completion(   ← AbstractClient, NOT LLMCaller (S7)

# ── documents / loader ──
# graphindex/extractors/loader.py:38 from parrot.stores.models import Document; :42 TYPE_CHECKING EbookSection; :198 local `from parrot.loaders.ebook import ebook_sections`
# graphindex/loader.py
from parrot.loaders.abstract import AbstractLoader                          # :31
from parrot.stores.models import Document                                   # :32
from parrot.knowledge.ontology.graph_store import OntologyGraphStore        # :34
from .embed import GraphIndexEmbedder                                       # :38
from .persist import GraphIndexPersistence                                  # :40
class _NullPersistence:                                                     # :44
class GraphIndexLoader(AbstractLoader):                                     # :96  (__init__ :130; _arango_params :180; _sqlite_dir :190)
    async def _make_persistence(self) -> Any:                               # :288  (sqlite :292-293; AsyncDB("arangodb") :299; OntologyGraphStore(arango_client=db) :305; GraphIndexPersistence :313)
        from navconfig import config                                        # :337
# stores/models.py: class Document(BaseModel) :19 (page_content, metadata)

# ── graph persistence ──
# graphindex/publish.py: class GraphPublisher :37; def __init__(self, persistence: Any, ctx: TenantContext) :47
# graphindex/persist.py
from parrot.knowledge.ontology.graph_store import OntologyGraphStore        # :36
class GraphIndexPersistence:                                                # :213  (Arango; uses graph_store.upsert_nodes/create_edges/soft_delete_nodes/get_all_nodes/query_documents/edges_incident/… )
    def __init__(self, graph_store: OntologyGraphStore) -> None             # :225
    persist_graph :235 · replace_document_slice :271 · load_graph :487 · apply_update :523 · get_commit :712 · list_commits :747 · revert_commit :789
# graphindex/persist_sqlite.py: class SQLitePersistence :138; __init__(db_dir) :153; _db_path :161; persist_graph :263; replace_document_slice :341; is_stale :464; load_graph :574; apply_update :608; get_commit :785; list_commits :817; revert_commit :856
# graphindex/persist_postgres.py: class PostgresPersistence :207; __init__ :226; close :256; is_stale :645; as_of :1175; history :1228; diff :1254; upsert_embeddings :1331; hybrid_retrieve :1484
# graphindex/pg_schema.py: import asyncpg :19; from navconfig import config :20; from pgvector.asyncpg import register_vector :21; from parrot.conf import default_dsn :23
# wiki/cli.py: SQLitePersistence imports :3995,4103,4558,4617; instantiations :4011, :4108 (inside GraphPublisher(...)), :4561, :4623
# flows/dev_loop/graph_memory.py: SQLitePersistence in the package import list :38; instantiation :142
# retrieval/pin.py: from ...persist_sqlite import SQLitePersistence :24; check_pin_coherence(pin, persistence: SQLitePersistence, ...) :378; db_path = persistence._db_path(ctx) :416
# contracts/temporal.py: persistence.as_of :361; .history :365; .diff :375
# parrot_tools/graphindex/toolkit.py: class GraphIndexToolkit(AbstractToolkit) :110; hasattr(persistence, "as_of") :306; hasattr(persistence, "hybrid_retrieve") :1326
# parrot_tools/graphindex/flowtask.py: from parrot.knowledge.graphindex.persist import GraphIndexPersistence :27; return GraphIndexPersistence(graph_store=store) :220 (MagicMock store)

# ── ontology ──
# ontology/graph_store.py
class OntologyGraphStore:                                                   # :53  ("ArangoDB wrapper")
    def __init__(self, arango_client: Any = None) -> None                   # :69
    async def _get_db(self, ctx) :73 · initialize_tenant :91 · _ensure_views :216 · _ensure_index :252
    async def execute_traversal(self, ctx, aql: str, bind_vars=None, collection_binds=None) -> list[dict]  # :271
    upsert_nodes :311 · create_edges :411 · get_all_nodes :488 · soft_delete_nodes :517 · ensure_collection :570 · get_document :598 · upsert_document :622 · insert_document :650 · remove_document :669 · query_documents :697 · get_all_edges :738 · edges_incident :764 · remove_edge_by_triple :791
# ontology/schema.py: class TraversalPattern :261 (query_template: str :288; post_query :290); class SearchViewDef :331; OntologyDefinition.traversal_patterns :443, .search_views :444; MergedOntology :452 (.traversal_patterns :476, .search_views :477); class TenantContext :529 (arango_db :542, pgvector_schema :543); class ResolvedIntent :547 (aql: str | None = None :571)
# ontology/intent.py: from .validators import validate_aql :25; class IntentDecision (aql :42); OntologyIntentResolver.__init__ :79; aql=pattern.query_template :150,212; validated = await validate_aql(decision.aql) :222; prompt '"aql": "<AQL query>" or null' :275
# ontology/validators.py: async def validate_aql(aql: str, max_depth: int | None = None) -> str :36 (reads parrot.conf.ONTOLOGY_MAX_TRAVERSAL_DEPTH lazily, conf.py:163)
# ontology/exceptions.py: OntologyError :4; AQLValidationError(OntologyError) :27
# ontology/authorization.py: from .graph_store import OntologyGraphStore :39; class AuthorizationChecker :43; __init__(self, graph_store: OntologyGraphStore, ...) :53-58; management-chain AQL :247-251 → execute_traversal :257; DOCUMENT().department AQL :334 → execute_traversal :339
# ontology/entity_resolver.py: import :25; __init__(graph_store: OntologyGraphStore) :116-122; _scope_filter :315 ("FILTER e.department == @user_department"); exact-match AQL :370-375 → execute_traversal :384; fuzzy AQL :413-420 → execute_traversal :427
# ontology/mixin.py: from parrot.auth.exceptions import AuthorizationRequired :65; from .graph_store import OntologyGraphStore :70; graph_store kwarg :120; self._ont_graph_store :130; execute_traversal(aql=intent.aql, ...) :337, :359, :379
# parrot_tools/legal/wiki_store.py: self._store = OntologyGraphStore(arango_client=client) :209; execute_traversal :265,321,354,439,448,467,480,486
# parrot_tools/legal/boe/sync.py: graph_store = OntologyGraphStore() :62
# parrot_tools/legal/boe/queries.py: store.execute_traversal(ctx, pattern.query_template, ...) :72, :176
# parrot_tools/procedures/retrieval.py: graph_store ctor :134-142; execute_traversal(self.tenant_context, self.aql_for(plan.pattern), ...) :292; def aql_for(self, pattern) -> str :311 (returns declared.query_template :320)
# parrot_tools/contracts/retrieval.py: graph_store ctor :265-273; def aql_for :681 (:695); execute_traversal :719

# ── wiki plane ──
# wiki/store.py: _EXTRA_BACKENDS :529; def register_wiki_backend(name, factory) :539; class BaseWikiStore(ABC) :553; class SQLiteWikiStore :948; def create_wiki_store(storage_dir, wiki_name="", backend="sqlite", **kwargs) :2665
# wiki/federation.py:418   factory = wiki_store._EXTRA_BACKENDS.get(cfg.backend)
# wiki/models.py:114   storage_backend: Literal["sqlite", "memory", "arangodb"] = Field(
# wiki/project.py: class WikiNamespaceConfig :186 (backend: str, free-form :224); WikiProjectConfig :561 (backend Literal :605; arango_database :616; storage_path branches :785-787); _navconfig :792; _env_credential :822; resolve_arango_params :851; sqlite_policy_from_config :928; WikiEnvOverlay :1026 (backend Literal :1063); resolve_wiki_env :1112
# wiki/sources.py: __init__ :144 (backend: Literal["sqlite","json","arangodb"] :148; arango_db/arango_store kwargs :149-150); sync Arango reads via _run_async(_arango_query(...)) :323,363,868,907; _run_async :1224; _resolve_arango_db :1289; _arango_query :1303; _arango_execute :1319; _async_upsert :1366; _async_upsert_many :1377; _async_list_sources :1387; _async_get_source :1395; _async_remove_source :1403; _async_find_id_by_uri :1411; _async_find_by_external_id :1419
# wiki/toolkit.py: SourceCollectionManager(backend=config.storage_backend ...) :139; sqlite :146; json :157,161; arangodb :159
# wiki/tools.py: from parrot.tools.abstract import AbstractTool, ToolResult :29; _scoped_store :32; _reject_foreign_id :58; _reject_managed_page :88; _qualify_ledger_target :123; _unknown_namespace_error :147; input models :166-226; WikiQueryTool :230 · WikiPageTool :272 · WikiRelatedTool :309 · WikiRememberTool :341 · WikiNoteTool :448 · WikiStatusTool :519 · WikiLintTool :552 · WikiStandupTool :605 · VaultIngestTool :665 · LedgerOpen/Ready/Claim/Close/ContextTool :829,864,885,904,929 · WikiPageHashesTool :1003 · WikiIngestBatchTool :1024 · WikiSyncPushTool :1098 · WikiSyncPullTool :1153; create_bulk_tools :1211; create_wiki_tools :1221
# wiki/toolkit.py: from parrot.tools.toolkit import AbstractToolkit :33; class LLMWikiToolkit :43
# wiki/structural/tools.py: from parrot.knowledge.wiki.tools import _scoped_store, _unknown_namespace_error :30; AbstractTool import :31; WikiSymbolLookupTool :106 · WikiCodeOutlineTool :146 · WikiBlastRadiusTool :181; create_structural_tools :226
# wiki/structural/toolkit.py: AbstractToolkit import :23; class CodeStructuralToolkit :26
# wiki/decisions/tools.py: AbstractTool import :28; WikiDecisionsForSymbolTool :100 · WikiDecisionWhyTool :140 · WikiDecisionGenerateTool :178; create_decision_tools :210 — decisions/toolkit.py: import :21; class DecisionToolkit :24
# wiki/schema/tools.py: AbstractTool import :14; _SchemaTool :44; Lookup/Search/Neighbors/Sources :68,92,104,116; create_schema_tools :128 — schema/toolkit.py: import :8; class SchemaPlaneToolkit :11
# wiki/mcp_server.py: from parrot.knowledge.wiki.tools import create_wiki_tools :29; StdioMCPServer import :34 (+ :389,:411); class WikiToolBundle :93; abuild_wiki_tools :105 (arangodb branch :133); ObsidianToolkit lazy import :303; build_wiki_tools :321; close_bundle :352; create_wiki_mcp_server :373; create_proxy_mcp_server :408; main :465
# wiki/serve.py: from parrot.knowledge.wiki.mcp_server import abuild_wiki_tools :156; close_bundle :196
# wiki/documents.py: `import aiohttp` is already function-local :583 (uses :587, :614)
# SQL dialect map consumers: wiki/cli.py:46 (click.Choice :3599,:3648); wiki/schema/render.py:14 (:47); wiki/schema/producers/ddl.py:13 (:219); tools/sql_dialects.py:27 `_SQLGLOT_DIALECT_MAP = SQLGLOT_DIALECT_MAP`
# wiki/cli.py: _env_setting :576; WIKI_STORE_BACKEND resolution :641,:658,:1612,:3958,:3966
# parrot_tools/business_automation/memory.py: `from parrot.knowledge.wiki.toolkit import LLMWikiToolkit` :31 (TYPE_CHECKING) and :110 (runtime)
# parrot_tools/legal/__init__.py:16-20 register_wiki_backend("ontology_legal", OntologyLegalWikiStore.factory)
# packages/ai-parrot/pyproject.toml:436  "mcp>=1.28.1,<2"  (core extra)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `Embedder` | `GraphIndexEmbedder.embed_nodes/get_embedding/search_similar` | structural typing | `embed.py:58,160,122` |
| `LLMCaller` | `PageIndexLLMAdapter.ask/ask_structured/ask_json` | structural typing | `llm_adapter.py:61,99,201` |
| `PageIndexer` | `PageIndexToolkit` six methods | injected into `GraphIndexBuilder` | `toolkit.py:404-857`, `builder.py:123` |
| `GraphPersistence` | `SQLitePersistence`, `PostgresPersistence`, `ArangoPersistence`, `NullPersistence` | structural typing + conformance suite | `persist_sqlite.py:263-987`, `persist_postgres.py:517-1003`, `persist.py:235-903`, `loader.py:44` |
| `create_graph_persistence` | the 7 dispatch sites | replaces direct construction | `factory.py:249`, `loader.py:288`, `runtime.py:91`, `cli.py:4011,4108,4561,4623`, `graph_memory.py:142` |
| capability Protocols | `GraphIndexToolkit`, `contracts/temporal.py` | `isinstance` | `toolkit.py:306,1326`, `temporal.py:361-375` |
| `GraphDocumentStore` | `ArangoPersistence.__init__` | injected | `persist.py:225` |
| `OntologyTraversalStore` | `AuthorizationChecker`, `EntityResolver`, `OntologyRAGMixin` | injected (existing kwargs) | `authorization.py:55`, `entity_resolver.py:116`, `mixin.py:120` |
| `execute_pattern` | `TraversalPattern` from ontology YAML | `pattern_for()` | `procedures/retrieval.py:311`, `contracts/retrieval.py:681`, `boe/queries.py:72,176` |
| `validate_query` | `OntologyIntentResolver` dynamic path | dispatch by dialect | `intent.py:222` |
| `resolve_wiki_backend` | `create_wiki_store`, `open_namespace_store` | one dispatch | `store.py:2665`, `federation.py:418` |
| `SourceManifestBackend` | `SourceCollectionManager`, `LLMWikiToolkit` | composition | `sources.py:148`, `toolkit.py:139-161` |
| `resolve_setting` | navconfig (lazy) | pattern already in `_navconfig` | `project.py:792` |
| `OperationDescriptor` | `WikiToolBundle`, SDK stdio server | `to_framework_tools` / `to_sdk_server` | `mcp_server.py:93,373,408` |
| `parrot_tools.wiki` | `AbstractToolkit` | subclass, as precedent | `parrot_tools/graphindex/toolkit.py:110` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.knowledge.graphindex.protocols` / `models` / `backends`~~, ~~`Embedder`, `LLMCaller`, `PageIndexer`, `GraphPersistence`, `IncrementalPersistence`, `TemporalGraphPersistence`, `EmbeddingPersistence`, `HybridRetrievalPersistence`, `ProviderNotAvailable`, `CapabilityUnavailable`, `GraphBackendSpec`, `register_graph_backend`, `create_graph_persistence`, `NullPersistence`~~ — created by this spec.
- ~~`parrot.knowledge.graphindex.persist_arango` / `ArangoPersistence`~~ — created by M7 (today `persist.py:GraphIndexPersistence`).
- ~~`parrot.knowledge.ontology.contracts`, `GraphDocumentStore`, `OntologyTraversalStore`, `DynamicQuery`, `ArangoOntologyGraphStore`, `register_ontology_backend`, `create_ontology_graph_store`, `validate_query`, `register_query_validator`, `QueryValidationError`, `QueryDialectMismatch`, `TraversalPatternUnavailable`, `TraversalPattern.query_templates`, `ResolvedIntent.query/dialect`~~ — created by M8.
- ~~A base class or Protocol for GraphIndex persistence~~ — `GraphPublisher.__init__(persistence: Any)` (`publish.py:47`); the builder probes `hasattr(…, "is_stale")` (`builder.py:505`).
- ~~A base class for the ontology graph store~~ — `OntologyGraphStore` is a concrete Arango wrapper (`graph_store.py:53-66`).
- ~~`OntologyGraphStore.execute_query` / `is_reachable` / `find_by_field` / `search_by_name` / `execute_pattern`~~ — only `execute_traversal(ctx, aql, …)` exists (`:271`).
- ~~`"arangodb"` in `build_graph_memory_toolkit`~~ — only `sqlite`/`postgres` (`factory.py:249-261`); Arango is reachable only via `GraphIndexLoader._make_persistence` (`loader.py:299-313`).
- ~~A `GraphIndexEmbedder` pgvector write path~~ — `_persist_to_pgvector` (`embed.py:193`) is a documented stub; durable vectors exist only in `PostgresPersistence.upsert_embeddings` (`:1331`).
- ~~`resolve_setting()`~~ — readers today: `_navconfig`/`_env_credential` (`project.py:792,822`), `_env_setting` (`cli.py:576`, `llm_resolve.py:11`), inline navconfig (`loader.py:337`), import-time constants in `pg_schema.py`.
- ~~`parrot/knowledge/common/sql_dialects.py`~~ — created by M4; today the map lives in `parrot/tools/sql_dialects.py:27`.
- ~~`parrot_tools.wiki`~~ — no such package (`parrot_tools/graphindex/` only has `__init__`, `flowtask`, `toolkit`).
- ~~`wiki/operations.py`, `wiki/transport.py`, `wiki/sources_backend.py`, `wiki/arango_sources.py`, `OperationDescriptor`, `SourceManifestBackend`, `wiki_backend_names`, `resolve_wiki_backend`, `create_source_backend`~~ — created by this spec.
- ~~`create_wiki_mcp_server(..., transport=)`~~ — no selector today; `StdioMCPServer` is imported inside the function (`mcp_server.py:389`).
- ~~A fixed six-tool MCP manifest~~ — the surface depends on configuration and mounted planes (`mcp_server.py:105-320`).
- ~~`mcp` SDK 1.29 as a new requirement~~ — `mcp>=1.28.1,<2` is already declared (`pyproject.toml:436`).
- ~~`HashingGraphEmbedder` in `embed.py`~~ — it is `factory.py:116`.
- ~~`wiki/documents.py` top-level `import aiohttp`~~ — already function-local (`:583`); the v0.1 Module 1 item is done.
- ~~`.mcp.json` as the wikitoolkit MCP registration~~ — the entry lives in `.claude/settings.local.json`.
- ~~`packages/parrot-graphindex/`, `parrot_graphindex`, `sys.meta_path` redirector~~ — FEAT-541.
- ~~HelixDB modules, extras, `docker/helixdb/`~~ — FEAT-670.
- ~~`LLMCaller` covering `OntologyIntentResolver`~~ — it calls `AbstractClient.completion` (`intent.py:176`) and stays framework-side.

### Edit Sites (Blueprint Anchors)

Verified against: `246f1bb6d` (2026-10-14). `/sdd-task` MUST re-run `grep -c` for every row it uses.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/auth/__init__.py` | MODIFY | `from .pbac import setup_pbac` | `:38` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/__init__.py` | MODIFY | `from .mixin import OntologyRAGMixin` | `:5` | 1 |
| `packages/ai-parrot/src/parrot/stores/__init__.py` | MODIFY | `from .abstract import AbstractStore` | `:5` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/__init__.py` | MODIFY | `from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence` | `:53` | 1 |
| `packages/ai-parrot/tests/knowledge/_support/import_probe.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/knowledge/test_import_ceilings.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/protocols.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/embeddings/graphindex.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/embed.py` | MODIFY | `from parrot.embeddings.registry import EmbeddingRegistry` | `:15` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/builder.py` | MODIFY | `from parrot.knowledge.pageindex.toolkit import PageIndexToolkit` | `:55` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/factory.py` | MODIFY | `    if backend == "sqlite":` | `:249` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/signals.py` | MODIFY | `    embedder: Optional["GraphIndexEmbedder"],` | `:395` | 1 (the three `= None` variants at `:466,528,557` are distinct lines) |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/retriever.py` | MODIFY | `        raw: list[tuple[str, float]] = await self.embedder.search_similar(` | `:321` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/triage.py` | MODIFY | `from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter` | `:42` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/classify.py` | MODIFY | `from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter` | `:9` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/links.py` | MODIFY | `from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter` | `:6` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py` | MODIFY | `from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter` | `:15` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py` | MODIFY | `        persistence = SQLitePersistence(config.graph_path(root))` | `:91` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/llm_resolve.py` | MODIFY | `def _env_setting(name: str) -> str \| None:` | `:11` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/operations.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/operations.py` · `decisions/operations.py` · `schema/operations.py` · `ledger/operations.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | MODIFY | `from parrot.tools.abstract import AbstractTool, ToolResult` | `:29` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` | MODIFY | `from parrot.tools.toolkit import AbstractToolkit` | `:33` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py` | MODIFY | `from parrot.tools.abstract import AbstractTool, ToolResult` | `:31` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py` | MODIFY | `from parrot.tools.toolkit import AbstractToolkit` | `:23` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/tools.py` | MODIFY | `from parrot.tools.abstract import AbstractTool, ToolResult` | `:28` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/toolkit.py` | MODIFY | `from parrot.tools.toolkit import AbstractToolkit` | `:21` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py` | MODIFY | `from parrot.tools.abstract import AbstractTool, ToolResult` | `:14` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/toolkit.py` | MODIFY | `from parrot.tools.toolkit import AbstractToolkit` | `:8` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/{__init__,tools,toolkit,structural,decisions,schema,ledger,bulk}.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/business_automation/memory.py` | MODIFY | `    from parrot.knowledge.wiki.toolkit import LLMWikiToolkit` | `:31` (runtime twin at `:110`, different indentation) | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `def _env_credential(key: str, default: Any) -> Any:` | `:822` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `    backend: Literal["sqlite", "memory", "arangodb"] = Field(default="sqlite")` | `:605` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | MODIFY | `    backend: Literal["sqlite", "memory", "arangodb"] \| None = None` | `:1063` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `def _env_setting(name: str) -> str \| None:` | `:576` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `from parrot.tools.sql_dialects import _SQLGLOT_DIALECT_MAP` | `:46` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `        persistence = SQLitePersistence(config.graph_path(root))` | `:4011`, `:4623` | **2** — `:4011` follows `from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence` at `:3995` inside the `graph build` command; `:4623` follows the import at `:4617` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `        publisher = GraphPublisher(SQLitePersistence(config.graph_path(root)), ctx)` | `:4108` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `                persistence = SQLitePersistence(config.graph_path(root))` | `:4561` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/pg_schema.py` | MODIFY | `from parrot.conf import default_dsn` | `:23` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/common/sql_dialects.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/render.py` | MODIFY | `from parrot.tools.sql_dialects import _SQLGLOT_DIALECT_MAP` | `:14` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/ddl.py` | MODIFY | `from parrot.tools.sql_dialects import _SQLGLOT_DIALECT_MAP` | `:13` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | `from parrot.knowledge.wiki.tools import create_wiki_tools` | `:29` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/serve.py` | VERIFY | `            from parrot.knowledge.wiki.mcp_server import abuild_wiki_tools` | `:156` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/models.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/extractors/loader.py` | MODIFY | `from parrot.stores.models import Document` | `:38` | 1 |
| `packages/ai-parrot/src/parrot/loaders/graphindex.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py` | MODIFY | `    async def _make_persistence(self) -> Any:` | `:288` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/loader.py` | MODIFY | `        from navconfig import config  # local import: optional dependency` | `:337` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/backends.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist.py` → `persist_arango.py` | RENAME + MODIFY | `    def __init__(self, graph_store: OntologyGraphStore) -> None:` | `:225` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_sqlite.py` | MODIFY | `class SQLitePersistence:` | `:138` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/persist_postgres.py` | VERIFY | `class PostgresPersistence:` | `:207` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/graphindex/publish.py` | MODIFY | `    def __init__(self, persistence: Any, ctx: TenantContext) -> None:` | `:47` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/graph_memory.py` | MODIFY | `        persistence = SQLitePersistence(Path(db_dir))` | `:142` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/contracts/temporal.py` | MODIFY | `        return await self.persistence.as_of(ctx, when)` | `:361` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/retrieval/pin.py` | MODIFY | `    db_path = persistence._db_path(ctx)` | `:416` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` | MODIFY | `        if persistence is not None and hasattr(persistence, "as_of"):` | `:306` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py` | MODIFY | `        if persistence is None or not hasattr(persistence, "hybrid_retrieve"):` | `:1326` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/graphindex/flowtask.py` | MODIFY | `        return GraphIndexPersistence(graph_store=store)` | `:220` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | MODIFY | `def register_wiki_backend(name: str, factory: Callable[..., BaseWikiStore]) -> None:` | `:539` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` | MODIFY | `    storage_backend: Literal["sqlite", "memory", "arangodb"] = Field(` | `:114` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` | MODIFY | `        backend: Literal["sqlite", "json", "arangodb"] = "sqlite",` | `:148` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources.py` | MODIFY | `    async def _arango_query(self, aql: str, bind_vars: dict[str, Any]) -> list[Any]:` | `:1303` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/sources_backend.py` · `arango_sources.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | MODIFY | `        factory = wiki_store._EXTRA_BACKENDS.get(cfg.backend)` | `:418` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py` | MODIFY | `class OntologyGraphStore:` | `:53` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` | MODIFY | `    query_template: str` | `:288` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` | MODIFY | `    aql: str \| None = None` | `:571` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/intent.py` | MODIFY | `                    validated = await validate_aql(decision.aql)` | `:222` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/validators.py` | MODIFY | `async def validate_aql(` | `:36` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py` | MODIFY | `class AQLValidationError(OntologyError):` | `:27` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py` | MODIFY | `                results = await self._graph_store.execute_traversal(` | `:257`, `:339` | **2** — `:257` is preceded by `bind_vars = {"asker_id": user_id, "target_id": target_id}`; `:339` by `bind_vars = {"target_id": target_id}` |
| `packages/ai-parrot/src/parrot/knowledge/ontology/entity_resolver.py` | MODIFY | `        return await self._graph_store.execute_traversal(` | `:384`, `:427` | **2** — `:384` ends `_exact_id_match` (AQL built at `:370-375`); `:427` ends `_fuzzy_name_match` (AQL at `:413-420`) |
| `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py` | MODIFY | `from .graph_store import OntologyGraphStore` | `:70` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/legal/wiki_store.py` | MODIFY | `            self._store = OntologyGraphStore(arango_client=client)` | `:209` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/sync.py` | MODIFY | `    graph_store = OntologyGraphStore()` | `:62` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/legal/boe/queries.py` | MODIFY | `    rows = await store.execute_traversal(` | `:72`, `:176` | **2** — `:72` inside the `article_in_force` lookup (binds `articulo_key`, `as_of`); `:176` inside the search pattern (binds `query`, `as_of`, `limit`) |
| `packages/ai-parrot-tools/src/parrot_tools/procedures/retrieval.py` | MODIFY | `        rows = await self.graph_store.execute_traversal(` | `:292` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/contracts/retrieval.py` | MODIFY | `        rows = await self.graph_store.execute_traversal(` | `:719` | 1 |
| `docs/graphindex/core-seams.md` · `sdd/state/FEAT-540/handoff-541.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **PEP 562 lazy root** — `__getattr__` + complete `__all__` + `__dir__`;
  cache resolved names in `globals()` (precedent: `wiki/__init__.py:56-120`,
  `graphindex/__init__.py:118-144`). Never delete a public name.
- **Protocols, not ABCs, for cross-package seams** (`graphindex/protocols.py`):
  `@runtime_checkable`, framework classes satisfy them without inheriting.
  Attribute presence is not signature compatibility — every consumer is tested
  against a typed double.
- **ABCs inside the ontology package** (`ontology/contracts.py`): the Arango
  store *does* inherit — the contract is intra-package and the ABC carries
  shared helpers (tenant scoping, pattern template resolution).
- **Registries are explicit `register_*` calls with lazy `module:callable`
  factories** (precedent: `register_wiki_backend`, `store.py:539`); core never
  imports a satellite; a satellite registers itself when imported (precedent:
  `parrot_tools/legal/__init__.py:16-20`). No entry points before FEAT-541.
- **Resolution order** — explicit argument → registered/built-in default →
  `ProviderNotAvailable` / `ValueError` naming the known names. Never a silent
  downgrade of an explicitly configured provider or backend.
- **Lazy imports name modules, not objects**, and live inside the function that
  needs them; `lazy_import(module, package, extra)` (`_imports.py:110`) for
  optional drivers so the error names the pip extra.
- **Hard cuts, no shims** for renamed internals (`GraphIndexPersistence` →
  `ArangoPersistence`, `OntologyGraphStore` → `ArangoOntologyGraphStore`,
  `ResolvedIntent.aql` → `query`, `aql_for` → `pattern_for`,
  `execute_traversal` → removed): there are no external consumers; every caller
  and test is updated in the same task. Old *public dotted paths* of moved
  symbols (`graphindex.embed.GraphIndexEmbedder`, `graphindex.loader.GraphIndexLoader`,
  `wiki.tools.*`, `wiki.toolkit.LLMWikiToolkit`, structural/decisions/schema
  tools) stay as lazy exports until FEAT-541's redirector.
- **AQL stays verbatim** when it moves into the Arango store's typed methods —
  the golden `captured_aql` fixture pins it.
- Google-style docstrings, strict type hints, Pydantic v2 models,
  `self.logger`, async-first, `aiohttp` only — per `CLAUDE.md`.

### Known Risks / Gotchas

- **Module counts are not measurable in-process.** Every ceiling assertion
  forks `python -I`; a failed import is reported as a failure, never as a low
  count.
- **`parrot/auth/__init__.py` is on the request path of the whole server.**
  A lazy root must keep every name resolvable and change only *when* callers
  pay; run auth/PBAC consumer suites, not only graph tests. Land it first.
- **`stores/__init__.py` must keep `extend_path` eager** (`:3`) or the
  `ai-parrot-embeddings` PEP 420 backends stop resolving.
- **`mcp_server.py:29` depends on what M3 moves** — sequence M3 before M5.
- **`structural/tools.py:30` imports two private helpers from `wiki/tools.py`**;
  they move to `wiki/operations.py`, never to `parrot_tools` (that would invert
  the dependency this spec exists to remove).
- **`embed.py:19` quiets FAISS at import**; the adapter keeps that behaviour
  for anything that relied on importing graphindex to silence faiss.
- **`SQLitePersistence` has no `close()`** today; adding a no-op is a behaviour
  change only in that callers may now call it — the factory/CLI must not start
  closing something they do not own (the Arango store owns its client).
- **`ArangoPersistence` needs the document/edge surface, not the typed one**
  (S6): typing it to `OntologyTraversalStore` would leak the Arango shape back
  into the "neutral" contract.
- **`TenantContext.arango_db` is still fabricated with synthetic names** by
  `authorization.py:240-245,328-333` and `entity_resolver.py:378-383,422-425`
  (`f"{tenant_id}_ontology"` + a mock ontology). M8 centralises that in one
  helper (`OntologyTraversalStore.scope(tenant_id, ontology)`) but does not
  rename the fields (§8 Q1).
- **Dynamic LLM-generated queries are a security boundary**: the fail-closed
  rule (no validator → no dynamic query) must be tested, and the AQL validator's
  existing tests must pass unchanged; the max-depth setting keeps reading
  `parrot.conf` lazily (`validators.py:36`) — it is not on an import ceiling path.
- **`search_views` are Arango-only** (`schema.py:331`); a neutral backend skips
  them with a logged warning — document that FTS parity is backend-specific.
- **`SourceCollectionManager` is sync with an async-bridge** (`_run_async`,
  `sources.py:1224`); the backend contract is async and the manager keeps the
  bridge — do not make the manager async in this feature.
- **Legacy `wiki_sources`/`sources` naming differs per backend**; parity tests
  compare behaviour, not storage layout.
- **Concurrent work on the same files**: FEAT-633 `parrot-installer`
  (TASK-4092/4093, `wiki/store.py:1107-1497`, `project.py:38-110` — 28 pending),
  FEAT-481 fireflies (16 in-progress, wiki ingest), FEAT-670 helixdb (spec in
  progress; depends on M7/M8 and must not start before they merge). Re-check at
  worktree creation.
- **Golden files drift**: manifests and `captured_aql` are regenerated only by
  an explicit `--update-golden` flag, never silently.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `mcp` | `>=1.28.1,<2` | already a core extra (`pyproject.toml:436`); SDK stdio transport |
| `navconfig` | unchanged | optional lazy credential provider — never a base import |
| `asyncdb` | unchanged | Arango driver behind `ArangoOntologyGraphStore` / `ArangoDBWikiStore` |
| `asyncpg`, `pgvector` | unchanged | Postgres backend, imported at selection |

No new third-party dependency is added by this spec.

---

## Worktree Strategy

**Isolation**: one feature worktree (`feat-FEAT-540-graphindex-core-seams`);
the `sdd-coder` engine gives each task its own sub-worktree inside it.

**Module dependency graph** (evidence in §3):

```
M1 ──► M2 ──► M6
 │      │
 ├────► M3 ──► M5
 ├────► M4 ──► M7 ◄── M8 (GraphDocumentStore type; TYPE_CHECKING first)
 │              │
 └────► M8      └──► M6 (loader persistence selection)
                M9 ◄── all
```

- M2 → M1 (ceiling harness proves the severing); M3 → M1; M4 → M1; M8 → M1
  (lazy ontology root).
- M5 → M3 (`mcp_server.py:29` imports what M3 moves).
- M7 → M4 (`resolve_setting` for Postgres/Arango options); M7 → M8 for the
  `GraphDocumentStore` annotation only.
- M6 → M2, M4, M7 (all three edit the old `graphindex/loader.py`).
- M3, M4, M8 have no edge between them and run concurrently after M1; M2 and
  M7 run concurrently with them except on the shared files below.

**Shared files** (their tasks get serialized):

| File | Modules |
|---|---|
| `graphindex/loader.py` | M2 (embedder import), M4 (navconfig block), M6 (relocation), M7 (persistence selection) |
| `graphindex/factory.py` | M2 (embedder wiring), M7 (dispatch) |
| `graphindex/builder.py` | M2 (types), M7 (`is_stale` capability) |
| `wiki/cli.py` | M4 (settings + SQL map), M7 (persistence sites), M3/M5 (symbol imports) |
| `wiki/project.py` | M4 (`resolve_setting`), M7 (backend Literals) |
| `wiki/runtime.py` | M2 (adapters), M7 (persistence) |
| `wiki/mcp_server.py` | M3 (imports), M5 (transport) |
| `graphindex/persist.py` → `persist_arango.py` | M7 (rename), M8 (type) |
| `ontology/__init__.py` | M1 (lazy root), M8 (renamed export) |
| `graphindex/__init__.py` | M1 (lazy exports), M6/M7 (new lazy names) |

**Exclusive resources**: none (no extension rebuild, lockfile or migration).
Golden-file regeneration tasks (M5 manifests, M8 `captured_aql`) must run
alone against a clean tree — mark them `parallel: false`.

**Cross-feature dependencies**: none blocking. FEAT-520 merged. **FEAT-541 and
FEAT-670 must not start until this spec is merged.** FEAT-633 and FEAT-481
overlap on `wiki/store.py` / `project.py` / ingest — reconcile at merge time.

---

## 8. Open Questions

**Resolved in the brainstorm — carried forward, not reopened:**

- [x] Flow type / base branch — *Resolved in brainstorm*: feature on `dev`.
- [x] Import name — *Resolved in brainstorm*: `parrot_graphindex` (FEAT-541).
- [x] Where does pageindex go — *Resolved in brainstorm*: split; this spec
      keeps the four adapter modules in core and reaches them through Protocols.
- [x] LLM-dependent CLI commands — *Resolved in brainstorm*: `LLMCaller`
      Protocol; without a provider the commands warn and are unavailable
      (`ProviderNotAvailable`, exit 2); optional-model paths keep degrading.
- [x] Backward-compat mechanism — *Resolved in brainstorm*: `sys.meta_path`
      finder in FEAT-541; this spec uses lazy old-path exports only.
- [x] Fate of `exp-lazy-ontology` — *Resolved in brainstorm*: discarded.
- [x] Versioning — *Resolved in brainstorm*: workspace member, lockstep (FEAT-541).
- [x] Phasing — *Resolved in brainstorm*: two FEATs.
- [x] navconfig — *Resolved in brainstorm*: optional lazy credential provider;
      realised by `resolve_setting()` (M4).
- [x] `HashingGraphEmbedder` location — `factory.py:116`, default `Embedder`.
- [x] `PageIndexer` surface — *Resolved 2026-10-14*: the six verified extractor
      calls (§2); `_content_store` stays an optional capability.
- [x] MCP transport selection — *Resolved 2026-10-14*: explicit keyword-only
      `transport=auto|framework|sdk`; `auto` falls back only on transport
      unavailability.
- [x] Scope of the graph-store seam — *Resolved by owner 2026-10-14*:
      persistence contract + registry **and** ontology typed traversals inside
      FEAT-540; HelixDB (FEAT-670) consumes them.
- [x] Task handling — *Resolved by owner 2026-10-14*: TASK-3256…3268 are
      superseded; `/sdd-task` re-decomposes from v0.4 with new IDs (§10).

**Still open:**

- [ ] **Q1 — `TenantContext.arango_db` / `pgvector_schema` and the Arango-shaped
      ontology schema** (`EntityDef.collection`, `RelationDef.edge_collection`,
      `SearchViewDef`): rename to neutral names with backend-provided handles
      (codex S4), or keep them and let non-Arango backends reinterpret them?
      This spec keeps them; a rename is a cross-cutting hard cut better taken
      with FEAT-670's data-model mapping. — *Owner: Jesus Lara*
- [ ] **Q2 — Dynamic query generation for non-AQL dialects**: fail closed
      (this spec) until a dialect registers a validator — should FEAT-670 ship
      a HelixDB validator, or should dynamic generation be AQL-only for good?
      — *Owner: Jesus Lara (decide in FEAT-670)*
- [ ] **Q3 — `legal` tools**: they stay explicitly Arango-bound
      (`execute_query(dialect="aql")`); should a later feature express their
      eight inline statements as ontology `TraversalPattern`s so they become
      portable? — *Owner: Jesus Lara* *(does not block this spec)*
- [ ] **Q4 — `pin.py` L0 coherence** is SQLite-only by design (S9). Should
      source-coherence become a `GraphPersistence` capability
      (`files_sample(ctx, n)`) so Postgres/HelixDB planes can be pinned? —
      *Owner: FEAT-670 / retrieval owner* *(does not block this spec)*
- [ ] **Q5 — Extras forwarding** (`ai-parrot[wiki]` → `parrot-graphindex[all]`)
      — FEAT-541 decision; this spec does not touch extras. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the exploration intent
> (standalone brainstorm + the owner's 2026-10-14 graph-store requirement; never
> over this spec). Model: `gpt-5.6-luna` (codex-cli 0.160.0, reasoning high) ·
> Status: **completed** (2026-10-14 18:00–18:02 UTC, exit 0, 12 suggestions,
> all `affected_paths` verified inside the repo) · Transcript:
> `sdd/state/FEAT-540/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Split pure core from framework adapters before enforcing ceilings (architecture) | CONFIRM | PEP 562 alone cannot meet G2; `graphindex/__init__.py` eager exports added to M1; Protocols/adapters are M2/M6 | §3 M1, M2, M6 |
| S2 | Behavioural persistence contract, not only a method Protocol (architecture) | CONFIRM | SQLite/Postgres/Arango differ in staleness, temporal, locking and error behaviour; semantics written into `GraphPersistence` + conformance suite | §2 `GraphPersistence` docstring, §3 M7, §4 `test_persistence_conformance` |
| S3 | One registry as the only composition root, incl. null and Arango (architecture) | CONFIRM | verified: `factory.py` sqlite/postgres, `loader.py` Arango + `_NullPersistence` (`:44`), 6 direct constructions; `null` becomes a registered backend | §2 `backends.py`, §3 M7 |
| S4 | Replace Arango-named `TenantContext` fields / isolate behind handles (api) | ESCALATE | correct observation (synthetic contexts at `authorization.py:240,328`); the rename is a cross-cutting hard cut best taken with FEAT-670's mapping; M8 centralises context fabrication without renaming | §8 Q1, §7 risks |
| S5 | Typed ops + dialect-bound dynamic escape hatch `{language, text, parameters}` (api) | CONFIRM | matches the owner's direction; realised as `OntologyTraversalStore` + `DynamicQuery` + `QueryDialectMismatch` + fail-closed `validate_query` | §2, §3 M8 |
| S6 | Keep GraphIndex persistence over a document/edge adapter, not the typed contract (architecture) | CONFIRM | `GraphIndexPersistence` uses `ensure_collection`, `query_documents`, `edges_incident`, soft deletes — split into `GraphDocumentStore` vs `OntologyTraversalStore` | §2 contracts, §3 M7/M8, §7 risk |
| S7 | Reconcile the LLM Protocol with callers using `completion` (api) | CONFIRM (scoped) | verified `intent.py:176`; the ontology resolver is framework-side and stays on `AbstractClient` — not folded into `LLMCaller`; the "distinguish `ProviderNotAvailable` from extraction failures" half is adopted | §3 M2, §6 Does-NOT-exist |
| S8 | Move durable embedding writes behind persistence capabilities (architecture) | CONFIRM | verified `embed.py:193` stub vs `persist_postgres.py:1331`; `EmbeddingPersistence` capability, `pgvector_dsn` removed from the embedder | §2, §3 M2/M7, §4 `test_embedder_no_pgvector_stub` |
| S9 | `pin.py` private SQLite path → explicit boundary or capability (risk) | CONFIRM | explicit SQLite-only guard now; capability deferred | §3 M7, §8 Q4 |
| S10 | Source-collection manager as an injected backend adapter (architecture) | CONFIRM | verified 25 `backend ==` branches in `sources.py` and selection in `toolkit.py:139-161`; `SourceManifestBackend` + registry | §2, §3 M7 |
| S11 | Build transport descriptors from one operation registry with fingerprints and duplicate checks (api) | CONFIRM | `OperationDescriptor.schema_fingerprint`, duplicate-name validation, per-mount golden manifests | §2, §3 M5 |
| S12 | Contract and import tests that verify behaviour, not counts (testing) | CONFIRM | conformance matrix, reopen tests, typed-projection and dynamic-rejection tests, blocked-package probes reusing `tests/test_minimal_install.py` | §4 |

Summary: **11** confirmed (one scoped) · **0** rejected · **1** escalated.

---

## 10. Task-contract refresh (supersession of the September decomposition)

TASK-3256…3268 (`sdd/tasks/index/graphindex-core-seams.json`, all `pending`,
no worktree, no code) were decomposed from v0.2 and assume the v0.2 file scopes
and anchors. v0.4 changes every module's file set and adds M7/M8. Per the
owner's decision they are **superseded**: on approval, `/sdd-task` re-decomposes
this spec with freshly reserved IDs and the thirteen files are closed as
`superseded` in the per-spec index (never implemented, never `done`). Until
then they must not be claimed.

| Superseded | Replaced by (module) |
|---|---|
| TASK-3256, 3257 | M1 |
| TASK-3258, 3259 | M2 |
| TASK-3260, 3261, 3262, 3263 | M3 (+ M5 descriptors) |
| TASK-3264 | M4 |
| TASK-3265 | M5 |
| TASK-3266, 3267 | M6, M7, M8 |
| TASK-3268 | M9 |

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-09 | Jesus Lara (with Claude) | Initial Option B phase-one specification. |
| 0.2 | 2026-09-10 | Jesus Lara (with Claude) | Identified the auth gateway and refreshed import measurements against `24ff50f03`. |
| 0.3 | 2026-10-14 | Codex | Re-verified against `048479633`: corrected provider, config, Postgres, SQL and MCP contracts; expanded relocation/compatibility gates; recorded the pending-task refresh. (Review form, not template form.) |
| 0.4 | 2026-10-14 | Jesus Lara (with Claude) | Rewritten in template form carrying the v0.3 findings with re-verified anchors; **scope widened** to a graph-database-agnostic persistence seam (M7: `GraphPersistence` + capabilities + registry, wiki backend registry, source backend) and a backend-neutral ontology contract (M8: `GraphDocumentStore` / `OntologyTraversalStore`, typed traversals, dialect-keyed patterns, fail-closed dynamic queries); codex design research folded (§9); TASK-3256…3268 superseded (§10); FEAT-670 (helixdb) now depends on this feature. |
