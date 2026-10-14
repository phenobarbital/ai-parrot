---
type: feature
base_branch: dev
---

# Feature Specification: GraphIndex Core Seams

**Feature ID**: FEAT-540
**Date**: 2026-09-09
**Reviewed**: 2026-10-14 against `dev` @ `04847963369264ca9622b0bcd2142566174db19c`
**Author**: Jesus Lara (with Claude); current-code review by Codex
**Status**: approved design; task contracts require refresh before implementation
**Target version**: 1.1.0

> Phase 1 of 2: cut framework seams inside the existing workspace.
> FEAT-541 (`parrot-graphindex-package`) owns the physical package move,
> distribution metadata and old-package redirector. It depends on this feature.
> Source: `sdd/proposals/parrot-graphindex-standalone.brainstorm.md` (Option B).
>
> This revision corrects the specification, not the implementation. All 13 tasks
> in `sdd/tasks/index/graphindex-core-seams.json` remain pending. Their September
> contracts and file scopes must be reconciled with §9 before execution.

## 1. Motivation and scope

GraphIndex and the LLM wiki support local repository indexing without an agent,
although eager imports currently load framework configuration, tools and provider
machinery. Core currently declares **59 runtime dependencies**. Moving directories
alone will not make these entry points independent.

The September measurements were historical observations, not current baselines.
Fresh subprocess measurements on Python 3.12.3 in the repository venv are recorded
in `artifacts/logs/FEAT-540-review-imports.json`. Relevant source is identical
between local `0c06b9c6b` and fetched remote `048479633`; the intervening changes
concern narration. Counts include the probe's `importlib`, `sys` and `json` imports.

| Entry point | Current modules | Target maximum |
|---|---:|---:|
| `parrot` | 99 | informational |
| `parrot.auth.exceptions` | 1093 | 150 |
| `parrot.knowledge.ontology.schema` | 1515 | 240 |
| `parrot.knowledge.graphindex` | 1877 | 800 |
| `parrot.knowledge.graphindex.builder` | 1986 | 1200 |
| `parrot.knowledge.wiki.cli` | 2202 | 850 |

All five feature entry points currently load forbidden heavy dependencies.
The target ceilings are retained from the approved design; they are targets,
not claims that the current implementation meets them. No current minimal-install
floor has been measured.

### Goals

- G1 — Meet all five import ceilings in fresh subprocesses, with no `navconfig`,
  `parrot.conf`, `navigator_eventbus`, `asyncdb`, `pandas`, `faiss`, `pyarrow`,
  `redis` or `asyncpg` module or submodule loaded.
- G2 — Remove eager runtime framework dependencies from graphindex/wiki,
  including indirect paths through PageIndex toolkits/adapters and SQL utilities.
- G3 — Preserve framework behavior through explicit providers and lazy adapters;
  retain hashing as the existing offline embedder default.
- G4 — Share plain operations, input schemas and result serialization between
  framework tools and SDK MCP transport. Preserve the complete current surface.
- G5 — Run local and remote-proxy stdio MCP with the framework MCP/tools modules
  blocked, while preserving the existing framework and HTTP-server consumers.
- G6 — Produce an audited extraction boundary for FEAT-541. Optional framework
  integrations must be explicitly inventoried; lazy imports alone do not make
  an integration standalone.

### Non-goals

- Create `packages/parrot-graphindex/`, rename imports to `parrot_graphindex`,
  implement the package redirector, or change dependency declarations/extras.
- Migrate wiki/graph/ledger/schema databases or change their schema versions.
- Replace database drivers, change retrieval/scoring semantics, or repair unrelated
  existing backend limitations.
- Move the Obsidian/Jira interfaces or all PageIndex code. FEAT-541 retains the
  agreed PageIndex split: pure tree/build/store code moves; `toolkit.py`,
  `llm_adapter.py`, `loader.py`, `pdf_to_markdown.py` remain framework adapters.
- Implement the feature as part of this specification review.

## 2. Verified current contracts

Paths below are relative to `packages/ai-parrot/src/parrot/`, except where noted.
Use symbols as anchors rather than the superseded September line numbers.

| Source | Verified contract / consequence |
|---|---|
| `auth/__init__.py` | Eager permission/resolver/PBAC/eval/userinfo/dataset exports; preserve every existing public name when making the root lazy. |
| `knowledge/ontology/__init__.py` | Eager cache, graph store, intent, mixin, schema and tenant exports. `mixin.py` reaches `auth.exceptions.AuthorizationRequired`. |
| `stores/__init__.py` | Eager `AbstractStore`; preserve `extend_path` and the complete `supported_stores` mapping, including `lancedb`. |
| `knowledge/graphindex/__init__.py` | Already has lazy exports, but also eagerly imports schema/signals/communities/persistence/extractors. Preserve both sets of exports. |
| `knowledge/graphindex/embed.py` | `GraphIndexEmbedder` eagerly imports `EmbeddingRegistry`, quiets FAISS logging and imports FAISS. |
| `knowledge/graphindex/factory.py` | `HashingGraphEmbedder` exists here. `build_graph_memory_toolkit` locally imports `parrot_tools.graphindex`; it consumes `embedder.index` and `embedder._node_id_map`, beyond the generic Embedder contract. |
| `knowledge/graphindex/builder.py` | Eager concrete embedder and PageIndex toolkit imports. Passes the embedder into resolution/signals; optionally reads PageIndex `_content_store` with `getattr`. |
| `knowledge/graphindex/retriever.py`, `signals.py` | Consume `search_similar` and `get_embedding`, respectively. An `embed_nodes`-only Protocol is insufficient. |
| `knowledge/graphindex/extractors/loader.py` | Imports `stores.models.Document`; PageIndex calls include six methods listed in §3. Ebook parsing also uses a local `parrot.loaders.ebook` import. |
| `knowledge/graphindex/loader.py` | `GraphIndexLoader` subclasses `AbstractLoader`, returns framework Documents and constructs framework providers. It belongs on the framework side. |
| `knowledge/graphindex/persist.py` | Imports `OntologyGraphStore` for an injected collaborator; move annotation-only coupling behind `TYPE_CHECKING`. |
| `knowledge/graphindex/pg_schema.py` | Eager `asyncpg`, `navconfig.config`, `pgvector.asyncpg` and `parrot.conf.default_dsn`; resolves DSN/schema/dimension at import. Missing from the old seam inventory. |
| `knowledge/wiki/project.py` | `_navconfig`, `_env_credential`, `resolve_arango_params`, `resolve_wiki_env`, `load_effective_config`, `sqlite_policy_from_config` already exist. Environment overlays and SQLite policy must survive. |
| `knowledge/wiki/llm_resolve.py` | Additional `_env_setting` and `resolve_optional_llm`; lazy factory/detection imports and intentional no-model fallback. |
| `knowledge/wiki/runtime.py`, `triage.py`, `inbox/{classify,links,processor}.py` | Provider construction and concrete PageIndex adapter coupling extend beyond the original triage scope. |
| `knowledge/wiki/cli.py`, `schema/render.py`, `schema/producers/ddl.py` | Import `_SQLGLOT_DIALECT_MAP` through `parrot.tools.sql_dialects`, triggering the tools package for plain data. |
| `knowledge/wiki/tools.py` | Core tools now include lint, standup, ledger and bulk sync, in addition to original query/page/related/remember/note/status/vault tools. |
| `knowledge/wiki/{structural,decisions,schema}/{tools,toolkit}.py` | All three planes have framework-facing wrappers requiring relocation. Structural-only relocation is incomplete. |
| `knowledge/wiki/mcp_server.py` | `WikiToolBundle`, `abuild_wiki_tools`, `build_wiki_tools`, `close_bundle`, `create_wiki_mcp_server`, `create_proxy_mcp_server`, `main` exist. Tool surface depends on configuration and mounted planes. |
| `knowledge/wiki/serve.py` | HTTP lifecycle calls `abuild_wiki_tools` and `close_bundle`; preserving only the stdio factory is insufficient. |
| `knowledge/wiki/documents.py` | `aiohttp` is already function-local, as is the egress wrapper; ebook acquisition uses framework loaders. Preserve this completed deferral and egress policy. |
| `knowledge/wiki/{jira_sync,jira_render,vault_scan,obsidian_sync}.py` | Jira/Obsidian integration dependencies remain; inventory them for FEAT-541 instead of asserting the whole tree is already portable. |

`graphindex/protocols.py`, `graphindex/models.py`, `resolve_setting` and
`parrot_tools.wiki` are proposed by this feature, not existing APIs.
The existing `wiki/models.py` is unrelated to the proposed graph document module.

## 3. Provider and document seams

Create `knowledge/graphindex/protocols.py` with runtime-checkable structural
Protocols. Framework classes must not inherit them. Keep this module's own
runtime imports stdlib-only; importing its package may still load allowed graph
model dependencies. Attribute-presence checks do not prove signature compatibility:
exercise each consumer against typed doubles as well.

| Protocol | Required surface |
|---|---|
| `Embedder` | `async embed_nodes(nodes: list[Any], batch_size: int = 64) -> list[Any]`; `get_embedding(node_id: str) -> Any | None`; `async search_similar(query: str, /, top_k: int = 10) -> list[tuple[str, float]]` |
| `LLMCaller` | Mirror `PageIndexLLMAdapter.ask(prompt, structured_output=None, temperature=0.0, system_prompt=None)`, `ask_structured(prompt, output_type, temperature=0.0, system_prompt=None)`, and `ask_json(prompt, temperature=0.0, system_prompt=None)` with their current return types. No unconstrained `*args/**kwargs` promise unsupported by concrete implementations. |
| `PageIndexer` | Async `list_trees() -> list[str]`, `create_tree(tree_name, doc_name=None)`, `delete_tree(tree_name)`, `get_tree(tree_name)`, `insert_markdown(tree_name, markdown, parent_node_id=None, doc_name=None)`, `insert_ebook(tree_name, sections, parent_node_id=None)`; all except `list_trees` return `dict[str, Any]`. |

The positional-only search query accommodates `query_text` in the concrete
embedder and `query` in hashing. Preserve existing score/distance semantics;
this feature does not normalize them. `_content_store` remains an optional
capability, not a required PageIndexer member. `ask_with_finish_info` is not
required by the verified consumers.

Move `GraphIndexEmbedder` to a framework adapter under `parrot/embeddings/`.
Preserve its old public path with a lazy compatibility export, including FAISS
logging behavior when explicitly requested. Retype builder, extractors,
retriever, signals, triage and inbox consumers. The generic graph path must not
inspect FAISS/private embedder fields: keep `build_graph_memory_toolkit`'s
concrete index wiring in a framework adapter, with a lazy compatibility entry.

Resolution order is explicit provider → built-in supported default →
`ProviderNotAvailable`. Automatic registration/entry points belong to FEAT-541;
do not describe a registry as already implemented. Framework entry points inject
real adapters when configured. Preserve optional-model fallback in
`resolve_optional_llm`; only operations requiring a provider raise
`ProviderNotAvailable(role, distribution, extra=None)`, mapped to CLI exit 2 with
an actionable message. Never silently downgrade an explicitly configured failing
provider to hashing or swallow its runtime failures as provider absence.

Create `GraphDocument(BaseModel)` in `graphindex/models.py` with
`page_content: str` and `metadata: dict[str, Any] = Field(default_factory=dict)`.
Define the minimal loader Protocol from actual `load()` consumers. Move
`GraphIndexLoader` to `parrot/loaders/graphindex.py`, keeping old imports lazy.
Core-side conversion preserves content and metadata; it does not claim to preserve
unrelated fields on richer framework Documents. Ebook helpers remain an explicitly
lazy optional adapter seam until their extraction ownership is resolved in FEAT-541.

## 4. Module breakdown

### M1 — Lazy package roots and measurement harness

Touch `auth/__init__.py`, `knowledge/ontology/__init__.py`, `stores/__init__.py`,
and focused tests; change `knowledge/wiki/documents.py` only if a regression is found. Preserve public exports,
namespace merging and dispatch mappings. Provide `__all__`, cached lazy resolution
and `__dir__` for discoverability; `__all__` alone does not implement `dir()`.
Verify the existing HTTP import deferral to acquisition paths. Preserve egress policy and error behavior.

Land the auth harness first. Run auth/PBAC consumer tests as well as graph tests.
Do not change `clients/base.py`.

### M2 — Providers and framework adapters

Implement §3. Scope includes graphindex `protocols`, `embed`, `builder`, `factory`,
`retriever`, `signals`, extractor annotations, wiki `triage`, `runtime`,
`llm_resolve`, and inbox adapter consumers; core-side adapter files and tests.
Keep annotation-only dependencies under `TYPE_CHECKING`. Explicitly test both
hashing/offline and framework-backed behavior without model downloads.

### M3 — Plain operations and all wiki wrappers

Extract framework-free operations and input schemas into wiki service modules.
Keep `_scoped_store`, `_unknown_namespace_error`, namespace/write guards, actor
context, locking, ledger ownership checks, error conversion and output budgeting
on the shared side. Do not duplicate business logic between transports.

Relocate wrappers into `packages/ai-parrot-tools/src/parrot_tools/wiki/`, including:

- Original wiki tools and `LLMWikiToolkit`, plus lint, standup and ledger tools.
- Structural, decision and schema tools and their toolkits.
- Bulk page-hash/ingest/sync tools and their registration gates.

Leave lazy old-path compatibility exports; importing those modules alone must
not load `AbstractTool`/`AbstractToolkit`. Requesting a legacy framework class may
load the framework. Internal plain consumers must never use these shims.
Keep schemas shared so SDK mode does not import `parrot_tools` to discover inputs.
Repoint business-automation memory, CLI symbol paths, package lazy exports,
MCP/HTTP consumers, relevant tests, and all discovered old-path consumers together.

### M4 — Configuration and SQL utility seams

Define a framework-free configuration resolver in `wiki/project.py`:

```python
def resolve_setting(
    key: str, *, default: Any = None, explicit: Any = None,
    project_defaults: Mapping[str, Any] | None = None,
) -> Any:
    """Resolve explicit, environment, optional navconfig, project default, fallback."""
```

`None` means absent; preserve explicit `False`, `0` and empty strings. Individual
callers may validate empty credentials. Check environment membership before
loading navconfig. A broken optional navconfig import logs only a safe diagnostic
at debug and falls through. `project_defaults` is explicitly supplied from effective
configuration; the resolver does not discover/read `wiki.json` or introduce a
project/config import cycle. Secrets remain environment-sourced, never persisted
in project defaults, error text or logs.

Consolidate credential/provider setting readers in `project.py`, `cli.py`,
`llm_resolve.py`, graph loader adapters and `pg_schema.py`. Preserve configuration
merge/overlay selection semantics. This is not a ban on every `os.environ` read
(e.g. subprocess environments, actor identity or feature switches).

Remove eager navconfig and `parrot.conf` imports from `pg_schema.py`; resolve
connection settings when the Postgres backend is selected. Framework wiring may
supply its existing default DSN explicitly. Standalone operation requires an
explicit/configured DSN; it never imports `parrot.conf` to synthesize one. Preserve
schema validation, dimension and FTS settings, and existing explicit DSN behavior.
Missing required connection settings fail before network I/O, naming keys without
values. A loopback endpoint explicitly configured by the user remains valid.
The old Arango implicit loopback fallback must not mask missing remote credentials;
cover this intentional behavior change in migration/error tests.

Move the plain SQL-dialect mapping to a neutral knowledge/common module, keeping a
compatibility export for existing tools consumers. Repoint CLI, schema rendering
and DDL producers. Do not add a dependency or copy divergent mappings.

### M5 — MCP transport and lifecycle

Build transport-neutral operation descriptors (name, description, input schema,
async invocation and result/error serialization), then adapt to framework tools or
SDK handlers. Preserve `WikiToolBundle` and the existing public assembly/cleanup
functions for HTTP consumers; separate plain assembly from wrapper construction.

SDK mode must work with `parrot.mcp`, `parrot.tools` and `parrot_tools` blocked,
for both local wiki and remote proxy. An explicit transport selector may be added
as a keyword-only argument (`auto`, `framework`, `sdk`) without changing existing
calls. `auto` prefers the available framework transport; fall back only for actual
transport unavailability, not arbitrary import/runtime/configuration failures.
Explicit framework mode reports missing dependencies; SDK mode never probes the
framework. Preserve clean JSON-RPC stdout and remote tool-list/call forwarding.

Capture golden tool manifests from the current implementation for each setup:
minimal local, ledger, decisions, schema plane present/absent, federated namespaces,
bulk enabled/disabled, vault configured, and remote proxy. Tool count is conditional;
there is no fixed six-tool contract. Compare canonical schemas, names, descriptions,
result/error payloads and registration conditions. Include actor propagation,
write-target rules, structural `read_repair`, SQLite policy and closure of owned
stores on shutdown/error/cancellation. Keep optional Obsidian framework tools gated
on their adapter; preserve the full set when that adapter is available and provide
an actionable capability error when explicitly requested without it.

`serve.py` continues using the existing HTTP stack; this feature does not introduce
another HTTP server framework. The SDK dependency already appears as
`mcp>=1.28.1,<2` in core extras; installed version 1.29.0 from the old spec is not a
new minimum requirement. Check the locked supported SDK API during implementation.

### M6 — Documents and loader relocation

Implement §3 after M2/M4 have finished edits to the old graph loader. Preserve
`GraphIndexLoader`'s constructor, `load()` behavior and old public import paths.
Test content/metadata conversion and extractor operation with a plain loader double.

### M7 — Ontology and optional database boundaries

Keep ontology schema models shared, with a lazy ontology root. Use injected
`OntologyGraphStore` and postponed annotations in `persist.py`. The relocated
framework loader may construct the graph store; standalone graph imports may not.

Keep drivers unchanged: wiki Arango uses `AsyncDB`; GraphIndex and wiki Postgres use
`asyncpg` with `pgvector` (not AsyncDB). Optional backend modules may import their
drivers when selected; default SQLite/CLI imports may not import them. M4 owns
Postgres configuration changes. Test both backend selection and default isolation.

## 5. Validation and acceptance

Use fresh subprocesses with a fixed probe/import order and the supported locked
Python environment. Assert successful imports before counts. Record interpreter
version, revision and loaded forbidden prefixes; a failed import is not a low count.
Heavy-package checks match both root names and dotted submodules.

- [ ] All five ceilings in §1 pass; none of the forbidden prefixes is loaded.
- [ ] AST scan of wiki/graphindex rejects eager runtime imports of `parrot.tools`,
  `parrot_tools`, `parrot.clients`, `parrot.loaders`, `parrot.stores`,
  `parrot.embeddings`, `parrot.conf`, and concrete PageIndex adapters/toolkits.
  Inspect executable module-level branches as well as direct imports; exempt
  annotation-only `TYPE_CHECKING`, not arbitrary `try`/`if` blocks.
- [ ] Dynamic import-blocker tests catch transitive/dynamic framework loads on the
  default entry points and plain operation paths. Lazy compatibility adapters are
  tested separately; do not exclude entire modules from the scan.
- [ ] Provider doubles exercise embedding, similarity lookup, vector retrieval,
  PageIndex extraction and LLM consumers; concrete classes satisfy the contracts.
- [ ] Default hashing remains deterministic; configured framework adapters work;
  required-provider errors exit 2 and optional-model paths still degrade safely.
- [ ] All current wiki tool families preserve canonical schemas and observable
  results/errors across framework and SDK paths for the configuration matrix in M5.
- [ ] MCP local/proxy SDK smoke tests pass with framework modules blocked; framework
  stdio and HTTP lifecycle tests still pass, including cleanup and clean stdout.
- [ ] Current recursive CLI command/option inventory is captured and preserved.
  Include newer remote/serve, ledger, decisions, schema, inbox and standup surfaces
  where registered; the September command list is not an exhaustive baseline.
- [ ] Settings precedence, falsey values, missing/broken navconfig, effective config
  overlays, explicit database configuration and secret-safe failures are covered.
- [ ] SQL dialect aliases produce identical render/DDL behavior after relocation.
- [ ] Existing wiki and graph planes reopen and query unchanged; deterministic
  fixture build/upsert counts match the pre-change baseline.
- [ ] Old public imports resolve lazily to the relocated classes/functions; new
  `parrot_tools.wiki` exports work. No eager shim reintroduces the import cost.
- [ ] Focused knowledge, auth/PBAC, loader, MCP/server and affected tools consumer
  suites pass, followed by `pytest packages/ai-parrot/tests/knowledge/ -v` and
  `pytest packages/ai-parrot-tools/tests/ -v` in the required test environment.
- [ ] `ruff check` on changed Python files and Black (120 columns) pass; new public
  symbols have type hints and Google-style docstrings. Save test logs under
  `artifacts/logs/`; distinguish unavailable live-backend tests from passing tests.
- [ ] FEAT-541 handoff inventories all remaining function-local optional framework
  imports with owner and behavior when absent, including Jira/Obsidian, ebooks,
  egress acquisition, coding-agent guard installers and framework toolkit factories.

This review ran import probes and static source verification only. It does not mark
any implementation acceptance criterion complete.

## 6. Compatibility and risks

- Lazy package roots affect server/auth consumers as well as wiki. Preserve symbol
  identity and namespace paths, and test callers rather than only module counts.
- Relocating wrappers while deleting old paths conflicts with the no-breaking-import
  requirement. Use lazy compatibility exports in FEAT-540; the whole-package
  redirector remains FEAT-541 work.
- Runtime-only optional adapters may legitimately load heavy dependencies after an
  explicit capability request. That is distinct from the default import gate.
- Do not replace egress-protected HTTP acquisition with unrestricted sessions.
- SDK schema equivalence alone is insufficient: preserve ToolResult error/content
  serialization, actor context and write guards.
- Existing third-party dependencies remain governed by workspace manifests/lock.
  No new library is authorized by this spec.
- September task scopes omit newer planes. Reconcile them before claiming tasks;
  do not silently implement outside a task's permitted files.

## 7. Worktree and sequencing strategy

Default isolation is `mixed`, but the current pending task DAG is not yet sufficient
for the expanded file scopes. Refresh ownership before scheduling implementation.

1. Land M1 auth harness and lazy roots.
2. Define M2 Protocols and M3 shared operations/schema contracts.
3. Finish M4 config/SQL seams, then retype consumers and relocate M6 loader.
4. Relocate all M3 wrappers and repoint consumers before M5 transport integration.
5. Complete M7 and run the final acceptance gate across all lanes.

`cli.py`, `project.py`, `mcp_server.py` and the old graph loader have shared ownership
across several modules: sequence their tasks instead of claiming they are disjoint.
FEAT-520 is already present; FEAT-541 remains dependent on this feature. Re-check
concurrent work and the baseline revision at implementation time.

## 8. Decisions and deferred questions

- Preserve two-feature phasing, `parrot_graphindex` import name, workspace/lockstep
  versioning, optional lazy navconfig and the previously agreed PageIndex split.
- PageIndexer scope is resolved by the six verified extractor methods (§3).
- Transport choice is deterministic/testable via explicit selection plus `auto`.
- No provider entry-point registry is introduced until FEAT-541.
- FEAT-541 must decide forwarding/deprecation of existing graph/wiki extras and
  disposition of optional Jira/Obsidian/ebook/egress and guard-install adapters.
  These are explicit handoff items, not proof that a blind directory move suffices.

## 9. Required task-contract refresh

Keep IDs and pending statuses. Refresh file ownership, blueprints, tests and index
notes/dependencies before execution; split expanded work with newly reserved task
IDs if it no longer fits an atomic task. Do not mark existing tasks completed from
this review.

| Existing tasks | Required reconciliation |
|---|---|
| TASK-3256–3257 | Current export inventories, five-entry harness, current baselines and egress-safe HTTP deferral. |
| TASK-3258–3259 | Complete Protocols; inbox/runtime/optional LLM consumers; concrete factory private-index boundary; lazy embedder compatibility. |
| TASK-3260–3263 | All current tool families, shared input schemas/operations, decision/schema/ledger/bulk surfaces and lazy old-path compatibility. Remove instructions that delete public paths outright. |
| TASK-3264 | Explicit project defaults, `llm_resolve`, Postgres config and neutral SQL mapping ownership; preserve effective config behavior. |
| TASK-3265 | Bundle async/sync APIs, HTTP consumer, proxy transport, configuration-dependent tool manifests, result serialization and cleanup. |
| TASK-3266–3267 | Loader compatibility, ebook seam, current ontology and driver boundaries; coordinate Postgres changes with TASK-3264. |
| TASK-3268 | Five successful import measurements, expanded AST/blocker checks, full CLI/MCP compatibility matrix and FEAT-541 residual-import inventory. |

## Revision history

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-09 | Jesus Lara (with Claude) | Initial Option B phase-one specification. |
| 0.2 | 2026-09-10 | Jesus Lara (with Claude) | Identified auth gateway and refreshed historical import measurements. |
| 0.3 | 2026-10-14 | Codex | Reverified current dev; corrected provider, config, Postgres, SQL and MCP contracts; expanded relocation/compatibility gates and recorded required pending-task refresh. |
