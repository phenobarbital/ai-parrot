---
type: Wiki Overview
title: FEAT-201 — ai-parrot-embeddings (split stores + embeddings + rerankers)
id: doc:sdd-proposals-ai-parrot-embeddings-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The original request, preserved verbatim. The full source (with the
relates_to:
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.handlers.stores
  rel: mentions
- concept: mod:parrot.registry.routing
  rel: mentions
- concept: mod:parrot.rerankers
  rel: mentions
- concept: mod:parrot.stores
  rel: mentions
- concept: mod:parrot.stores.kb
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot.stores.parents
  rel: mentions
- concept: mod:parrot.stores.pgvector
  rel: mentions
- concept: mod:parrot.stores.utils
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.vectorstoresearch
  rel: mentions
---

---
id: FEAT-201
title: Split parrot.embeddings/stores/rerankers into a new ai-parrot-embeddings sibling package via namespace extension
slug: ai-parrot-embeddings
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-28
  summary_oneline: Move stores + embeddings + rerankers concrete backends into a new ai-parrot-embeddings package; keep Registries / Abstracts in core; preserve imports via namespace extension
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-201/
created: 2026-05-28
updated: 2026-05-28
---

# FEAT-201 — ai-parrot-embeddings (split stores + embeddings + rerankers)

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` (no Jira ticket attached)
> **Audit**: [`sdd/state/FEAT-201/`](../state/FEAT-201/)

---

## 0. Origin

The original request, preserved verbatim. The full source (with the
follow-up clarifications captured during the plan-gate phase) is at
`sdd/state/FEAT-201/source.md`.

**Original (Spanish):**

> ai-parrot-embeddings -- convertir los extras de embeddings (con extras
> [arangodb|milvus|bigquery|faiss|pgvector|...]) en paquete aparte, la
> infra "base" (Registry de Embeddings, Abstract) se mantiene en
> ai-parrot pero los embeddings de cada tipo se instalan con extras del
> paquete nuevo `ai-parrot-embeddings`
> (ejemplo: `ai-parrot-embeddings[pgvector]`).

**Clarifications (gate phase):**

> 1. *"move stores, embeddings, rerankers to new package
>    ai-parrot-embedding, that is the requirement."*
> 2. *"if we install from an external package, the import phase will
>    stay equal? like (from parrot.stores ...) but comes from
>    ai-parrot-embeddings?"*
> 3. *"my decision is PEP 420 (namespace package), the other packages
>    were moved without take care of PEP 420, but let's stay
>    ai-parrot-embeddings using "B" choice."*

**Initial signals** (extracted, not interpreted):

- Verbs: *convertir*, *mantiene*, *instalan*, *move*, *stay using B choice* → enrichment (additive packaging change)
- Named entities: `ai-parrot-embeddings`, `EmbeddingRegistry`, `Abstract`, `parrot.stores`, `parrot.embeddings`, `parrot.rerankers`, `pgvector`, `milvus`, `arangodb`, `bigquery`, `faiss`, `PEP 420`
- Components / labels: none (inline source)
- Acceptance criteria provided: no — proposal phase will draft them

---

## 1. Synthesis Summary

FEAT-201 creates a new sibling distribution `ai-parrot-embeddings` under
`packages/` that owns the **concrete backends** of three subsystems
currently in core: `parrot.embeddings.{google,huggingface,openai}`,
`parrot.stores.{postgres,milvus,arango,bigquery,faiss_store,pgvector}`,
and `parrot.rerankers.{local,llm}`. The **base infrastructure**
(Registries, Abstracts, dispatch maps, shared types, factories) stays in
`ai-parrot` core, where it already resolves backends by import string —
so the split has zero runtime API impact. Crucially, the new package
ships its modules **under the existing `parrot.*` namespace** (via
pkgutil-style namespace extension that the host already opts into in
`packages/ai-parrot/src/parrot/__init__.py:12`), so every existing
`from parrot.stores.pgvector import PgVectorStore` site stays
byte-identical — no `__getattr__` proxies, no `parrot_embeddings.*`
top-level rename. This deliberately breaks with the
`ai-parrot-tools/-loaders/-pipelines` precedent (which all use separate
top-levels + `sys.meta_path` redirectors) and makes FEAT-201 the first
real exercise of namespace extension in this repo.

---

## 2. Codebase Findings

> All entries are grounded in the digests at
> `sdd/state/FEAT-201/findings/F001-...F014`. **No fabricated paths or
> symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
|  1 | `packages/ai-parrot/src/parrot/__init__.py` | `extend_path(__path__, __name__)` | 1-31 | Host top-level. **Already** opts into pkgutil namespace extension so siblings can contribute under `parrot.*` | F001 |
|  2 | `packages/ai-parrot/pyproject.toml` | `[tool.setuptools.packages.find]` | 529-532 | Host package-discovery. **Already** declares `namespaces = true` + `include = ["parrot*"]` | F002 |
|  3 | `packages/ai-parrot/src/parrot/embeddings/` | embeddings sub-package (9 files) | — | 3 backends (google, huggingface, openai) MOVE; base/registry/catalog/matryoshka/processor STAY | F003 |
|  4 | `packages/ai-parrot/src/parrot/embeddings/registry.py` | `EmbeddingRegistry._build_model` | 149-178 | Dispatcher resolves backends by `importlib.import_module(f"parrot.embeddings.{model_type}")` — string-based, no compile-time coupling | F006 |
|  5 | `packages/ai-parrot/src/parrot/embeddings/base.py` | `EmbeddingModel` (ABC) | 15-228 | Abstract base — STAYS in core | F003 |
|  6 | `packages/ai-parrot/src/parrot/embeddings/__init__.py` | `supported_embeddings` dict | 14-18 | Dispatch table (`huggingface`/`google`/`openai` → class names) — STAYS in core | F006 |
|  7 | `packages/ai-parrot/src/parrot/stores/` | stores sub-package (28 files) | — | 6 concrete top-level backends MOVE; abstract/models/empty/cache + sub-packages `kb/`, `parents/`, `utils/` STAY (see C10) | F004 |
|  8 | `packages/ai-parrot/src/parrot/stores/__init__.py` | `supported_stores` dict | 1-10 | Dispatch table (`postgres`/`milvus`/`kb`/`faiss_store`/`arango`/`bigquery` → class names) — STAYS in core | F007 |
|  9 | `packages/ai-parrot/src/parrot/stores/abstract.py` | `AbstractStore` | — | Abstract base — STAYS in core | F004, F012 |
| 10 | `packages/ai-parrot/src/parrot/stores/models.py` | `Document`, `SearchResult`, `StoreConfig`, `DistanceStrategy` | — | Shared types consumed by rerankers/bots/handlers/manager/knowledge — STAYS in core | F012 |
| 11 | `packages/ai-parrot/src/parrot/stores/postgres.py` | `PgVectorStore` | 49 | PgVector backend — MOVES → `ai-parrot-embeddings[pgvector]` | F004 |
| 12 | `packages/ai-parrot/src/parrot/stores/milvus.py` | `MilvusStore` | 67 | Milvus backend — MOVES → `[milvus]` | F004 |
| 13 | `packages/ai-parrot/src/parrot/stores/arango.py` | `ArangoDBStore` | 28 | Arango backend — MOVES → `[arango]` | F004 |
| 14 | `packages/ai-parrot/src/parrot/stores/bigquery.py` | `BigQueryStore` | 23 | BigQuery backend — MOVES → `[bigquery]` | F004 |
| 15 | `packages/ai-parrot/src/parrot/stores/faiss_store.py` | `FAISSStore` | — | FAISS backend — MOVES → `[faiss]` (note: faiss-cpu lib stays in core deps for episodic memory) | F004, F008 |
| 16 | `packages/ai-parrot/src/parrot/rerankers/` | rerankers sub-package (6 files) | — | 2 concrete rerankers MOVE; abstract/models/factory/__init__ STAY | F005 |
| 17 | `packages/ai-parrot/src/parrot/rerankers/__init__.py` | `__getattr__` lazy loader | 30-50 | Lazy backend loading already implemented — works unchanged after move | F005 |
| 18 | `packages/ai-parrot/src/parrot/rerankers/factory.py` | `create_reranker` | 26-83 | Factory with local imports for concrete classes — STAYS in core | F005 |
| 19 | `packages/ai-parrot/src/parrot/rerankers/local.py` | `LocalCrossEncoderReranker` | — | Cross-encoder reranker — MOVES → `[reranker-local]` | F005 |
| 20 | `packages/ai-parrot/src/parrot/rerankers/llm.py` | `LLMReranker` | — | LLM-based reranker — MOVES → `[reranker-llm]` | F005 |
| 21 | `packages/ai-parrot/pyproject.toml` | `embeddings`, `bigquery`, `arango`, `milvus`, `chroma` extras + `all` / `all-fast` meta-extras + `pgvector` (inside `images`!) + core dep `faiss-cpu` | 287-308, 124-126, 172-174, 408-411, 413-415, 503-510, 352, 96-99 | Extras inventory — most move/redistribute, faiss-cpu stays in core deps | F008 |
| 22 | `packages/ai-parrot-tools/pyproject.toml` | per-backend extras + workspace dep | 33-72, 81-92 | Closest precedent for the new package's shape | F009 |
| 23 | `packages/ai-parrot/src/parrot/tools/__init__.py` | `_ParrotToolsRedirector` | 50-65 | Sibling-precedent's `sys.meta_path` redirector — FEAT-201 deliberately does NOT use this pattern | F010 |
| 24 | `packages/ai-parrot/src/parrot/handlers/stores/` | handlers/stores tree | — | HTTP handlers for vector stores — STAY in core | F014 |
| 25 | `packages/ai-parrot/src/parrot/registry/routing/store_router.py` | `StoreRouter` | 32-33 | Routing layer wiring `AbstractStore` + `MultiStoreSearchTool.StoreType` — STAYS in core | F014 |
| 26 | `packages/ai-parrot/src/parrot/tools/__init__.py` | `VectorStoreSearchTool`, `MultiStoreSearchTool` | 243-244 | Core RAG-primitive tools (per FEAT-057 explicit decision) — STAY in core | F014 |
| 27 | `packages/ai-parrot/src/parrot/bots/abstract.py` | lazy stores/embeddings imports | 82-85, 1436 | AbstractBot already uses lazy local imports for backends — pattern preserved | F012 |
| 28 | `sdd/specs/monorepo-migration.spec.md` | FEAT-057 decision: proxy modules, NOT PEP 420 | 34, 116-120 | Prior precedent FEAT-201 deliberately breaks from | F011 |
| 29 | `sdd/specs/formdesigner-package.spec.md` | FEAT-079 decision: PEP 420 (spec, not impl) | 371-384 | Aspirationally aligned precedent; not actually exercised in implementation | F011 |

### 2.2 Constraints Discovered

- **Host already opts into namespace extension at the top level**
  (`parrot/__init__.py:12` calls `extend_path`), but the three target
  sub-packages (`parrot/embeddings/`, `/stores/`, `/rerankers/`) do
  **not** call it. *Implication*: FEAT-201 must add a one-line
  `extend_path` to each of the three sub-package `__init__.py` files so
  satellite-supplied modules become reachable through the existing
  namespace.
  *Evidence*: F001

- **All three dispatch layers resolve backends by import string** —
  `EmbeddingRegistry._build_model` uses `importlib.import_module`;
  `parrot.stores` exposes a `supported_stores` name map; rerankers' init
  uses module-level `__getattr__`. *Implication*: zero changes to
  dispatcher code in core; backends become reachable at the same import
  paths after the move.
  *Evidence*: F005, F006, F007

- **`parrot.stores.models` is a shared-types module** (Document,
  SearchResult, StoreConfig, DistanceStrategy) imported by rerankers,
  bots, handlers, manager, knowledge, scraper, and the in-flight
  parent-child retrieval module. *Implication*: `models.py` MUST stay in
  core. Backends that move continue to import it at runtime —
  byte-identical under namespace extension.
  *Evidence*: F012

- **`faiss-cpu` is a core dependency** of `ai-parrot` (line 98 of host
  pyproject) because episodic memory uses it as a default fallback.
  *Implication*: moving `FAISSStore` to the satellite is fine, but
  `faiss-cpu` MUST stay in core deps — not relegated to an extra.
  *Evidence*: F008

- **`pgvector` currently lives inside the `images` extra** (line 352 of
  host pyproject), not its own extra. *Implication*: introduce
  `ai-parrot-embeddings[pgvector]` carrying pgvector, and amend the
  host's `images` extra (drop pgvector or declare
  `ai-parrot-embeddings[pgvector]` as a dep).
  *Evidence*: F008

- **Meta-extras `all` and `all-fast`** (lines 505 and 509 of host
  pyproject) reference the `embeddings` extra. *Implication*: after the
  split, both must be rewritten to pull from `ai-parrot-embeddings[...]`
  to preserve the legacy one-liner install UX.
  *Evidence*: F008

- **All existing sibling packages** (`-tools`, `-loaders`, `-pipelines`,
  `parrot-formdesigner`) ship under separate top-levels with
  `sys.meta_path` redirectors in core. The FEAT-079 plan for PEP 420 in
  TASK-548 was approved but the actual implementation reverted to
  `parrot_formdesigner.*`. *Implication*: FEAT-201 is the **first real
  exercise** of namespace extension in this repo — small but real risk;
  flag for QA (verify byte-identical imports + editable-install
  coexistence in a clean environment).
  *Evidence*: F010, F011

- **All three subsystems have active recent work** (matryoshka FEAT-150,
  contextual embedding FEAT-127/128, PgVector metadata_filters,
  parent-child retrieval factory FEAT-128/133, reranker factory
  FEAT-133) but **no in-flight SDD spec touches packaging**.
  *Implication*: no collision risk on namespace boundaries, but the
  Matryoshka kwarg-forwarding wiring through `AbstractStore.create_embedding`
  and `SentenceTransformerModel` must be re-tested after the move.
  *Evidence*: F013

### 2.3 Recent History (Relevant)

Commits on the affected paths in the last 90 days, ordered newest first.

| Commit | Theme | Touched files |
|--------|-------|---------------|
| `2c72af9c` | embedding catalog | `parrot/embeddings/catalog.py` |
| `2f37c5b3` / `7f2d5b99` / `d48ec222` / `fe949c6d` / `b3f25477` | FEAT-150: Matryoshka embedding truncation | `embeddings/registry.py`, `embeddings/huggingface.py`, `embeddings/matryoshka.py` |
| `c5904533` | TASK-1087: PgVectorStore metadata_filters extension | `stores/postgres.py` |
| `ff1f5435` | TASK-1037: FAISS S3 persistence | `stores/faiss_store.py` |
| `84ce2866` | TASK-1037: AbstractStore.create_embedding forwards matryoshka kwarg | `stores/abstract.py` |
| `8647fb87` | FEAT-128 TASK-906: parent-child retrieval factory | `stores/parents/factory.py` |
| `f3f80ee1` / `66475ac2` / `595544e9` | FEAT-127: contextual embedding wiring into Milvus/FAISS/Arango/PgVector stores | `stores/*` |
| `499c4d18` | FEAT-133 TASK-905: rerankers factory | `rerankers/factory.py` |
| `bc927376` / `18b1c64e` / `b0f171fa` | TASK-863/864/865: LocalCrossEncoderReranker + LLMReranker + base models | `rerankers/{local,llm,abstract,models}.py` |

*Evidence*: F013

---

## 3. Probable Scope

### What's New

- **`packages/ai-parrot-embeddings/pyproject.toml`** — name
  `ai-parrot-embeddings`, depends on `ai-parrot`, declares per-backend
  optional-dependencies (`pgvector`, `milvus`, `arango`, `bigquery`,
  `faiss`, `chroma`, `openai`, `google`, `huggingface`, `reranker-local`,
  `reranker-llm`, `all`), uses `setuptools.packages.find` with
  `include = ["parrot*"]` + `namespaces = true`, and registers as a uv
  workspace member (`[tool.uv.sources] ai-parrot = { workspace = true }`).
- **`packages/ai-parrot-embeddings/src/parrot/embeddings/{google,huggingface,openai}.py`** — concrete embedding backends. **No `__init__.py`** at `parrot/` or `parrot/embeddings/` in the satellite (pure PEP 420 per U3).
- **`packages/ai-parrot-embeddings/src/parrot/stores/{postgres,milvus,arango,bigquery,faiss_store,pgvector}.py`** — concrete vector-store backends. **No `__init__.py`** at `parrot/stores/` in the satellite.
- **`packages/ai-parrot-embeddings/src/parrot/rerankers/{local,llm}.py`** — concrete rerankers. **No `__init__.py`** at `parrot/rerankers/` in the satellite.
- **Workspace registration**: root `pyproject.toml` `[tool.uv.workspace]`
  members list gains the new package.
- **Per-backend pytest markers** in the new package's tests mirroring
  per-backend extras (e.g. `@pytest.mark.requires_pgvector`).
- **Wheel-content verification test** ensuring the satellite wheel
  contains **no** `__init__.py` at `parrot/`, `parrot/embeddings/`,
  `parrot/stores/`, or `parrot/rerankers/` (locks the U3 decision into
  CI).

### What Changes

- **`packages/ai-parrot/src/parrot/embeddings/__init__.py`** — keeps
  `supported_embeddings` and re-exports unchanged. Under pure PEP 420
  semantics for the satellite, this `__init__.py` continues to define
  the regular package `parrot.embeddings`; satellite-supplied modules
  (`google.py`, `huggingface.py`, `openai.py`) become reachable because
  setuptools merges directories with the same dotted name from multiple
  installed distributions when the package-discovery is namespace-aware
  (F002). **Spec must validate this empirically** — if discovery fails,
  add a one-line `__path__ = extend_path(__path__, __name__)` (kept as
  a fallback in the spec).
  *Evidence*: F001, F002, F006
- **`packages/ai-parrot/src/parrot/stores/__init__.py`** — same
  consideration; `supported_stores` map stays unchanged.
  *Evidence*: F001, F002, F007
- **`packages/ai-parrot/src/parrot/rerankers/__init__.py`** — same
  consideration; lazy `__getattr__` stays unchanged.
  *Evidence*: F001, F002, F005
- **`packages/ai-parrot/pyproject.toml`** — remove the `embeddings`,
  `milvus`, `chroma`, `arango`, `bigquery` extras (or replace each with
  a thin dependency on `ai-parrot-embeddings[<key>]`); extract
  `pgvector==0.4.1` from the `images` extra (line 352) and either drop
  it or amend `images` to declare `ai-parrot-embeddings[pgvector]` as a
  dep; rewrite the `all` (line 505) and `all-fast` (line 509)
  meta-extras to reference `ai-parrot-embeddings`; **keep**
  `faiss-cpu>=1.9.0` in core dependencies (line 98) for episodic memory.
  *Evidence*: F008
- **Delete** the moved backend files from
  `packages/ai-parrot/src/parrot/{embeddings,stores,rerankers}/` once
  the new package builds and tests pass.

### What's Untouched (Non-Goals)

- **Public API surface** — every `from parrot.{embeddings,stores,rerankers}.X import Y`
  site stays byte-identical (the load-bearing user requirement, C2).
- **`EmbeddingRegistry`, `AbstractEmbeddingModel`, `AbstractStore`,
  `AbstractReranker`** — all stay in core unchanged.
- **Dispatch tables** (`supported_embeddings`, `supported_stores`) and
  rerankers' `__init__` lazy `__getattr__` — stay in core unchanged.
- **Shared types**: `parrot.stores.models` (Document, SearchResult,
  StoreConfig, DistanceStrategy) — stays in core.
- **Higher-level orchestration sub-packages**: `parrot.stores.kb`,
  `parrot.stores.parents`, `parrot.stores.utils` — likely stay in core
  (revisit in spec; see U2).
- **Core RAG-primitive tools**: `parrot.tools.vectorstoresearch`,
  `parrot.tools.multistoresearch` — stay in core (per FEAT-057 explicit
  decision in `sdd/specs/monorepo-migration.spec.md:131-132`).
- **HTTP handlers** `parrot.handlers.stores` — stay in core.
- **Routing layer** `parrot.registry.routing` — stays in core.
- **Existing sibling packages** (`ai-parrot-tools`, `-loaders`,
  `-pipelines`, `parrot-formdesigner`) and their `parrot_<name>.*` +
  redirector machinery — **not touched**; FEAT-201 introduces a new
  convention **alongside** the old one, not a retrofit.

### Patterns to Follow

- **uv-workspace + setuptools `src/` layout** mirroring
  `packages/ai-parrot-tools/` (F009).
- **Per-backend optional-dependencies** block with an `all` aggregator
  extra (F009).
- **`[tool.uv.sources] ai-parrot = { workspace = true }`** for editable
  workspace dev (F009).
- **Dispatch-by-import-string** idiom already used by
  `EmbeddingRegistry` (F006) — no change needed.
- **Lazy / circular-avoiding local imports** for heavy backends already
  idiomatic in bots/handlers/manager (F012) — preserved unchanged.

### Integration Risks

- **First-of-its-kind namespace extension in this repo.** TASK-548's
  plan for PEP 420 reverted to `parrot_<name>.*` in implementation, so
  FEAT-201 is the first real exercise. *Mitigation*: explicit pytest
  proving that `from parrot.stores.pgvector import PgVectorStore` works
  both **with** the satellite installed and produces a clear, actionable
  `ImportError` **without** it. Evidence: F010, F011.
- **`images` extra entanglement** (pgvector currently bundled). *Mitigation*:
  extract pgvector to `ai-parrot-embeddings[pgvector]` and amend
  `images` to declare it as a dep. Evidence: F008.
- **Meta-extra UX regression.** Users running `pip install ai-parrot[all]`
  must still get the full functional stack. *Mitigation*: rewrite `all`
  to `ai-parrot[...] + ai-parrot-embeddings[all]`; document in release
  notes. Evidence: F008.
- **Matryoshka and contextual-augmentation wiring** (FEAT-150,
  FEAT-127/128) cross the boundary at
  `AbstractStore.create_embedding` ↔ `SentenceTransformerModel`.
  *Mitigation*: keep the existing matryoshka/contextual test suite
  green against the satellite-installed environment. Evidence: F013.
- **Editable-install IDE friction.** Workspaces where both
  distributions contribute to `parrot.*` can confuse IDEs. *Mitigation*:
  document `uv sync --all-packages` dev workflow; CI gate verifies
  import resolution. Evidence: F010.

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Scope = stores + embeddings + rerankers (3 subsystems) | user clarification (in `source.md`) | high | Direct user quote |
| C2 | Imports must stay byte-identical (`from parrot.stores import …`) | user clarification (in `source.md`) | high | Direct user quote |
| C3 | Host `parrot/__init__.py` already calls `extend_path` for namespace extension | F001 | high | Direct read |
| C4 | Host pyproject declares `namespaces = true` under `setuptools.packages.find` | F002 | high | Direct read; lines 529-532 |
| C5 | `EmbeddingRegistry` resolves backends by `importlib.import_module(f"parrot.embeddings.{model_type}")` — no compile-time coupling | F006 | high | Direct read of `registry.py:149-178` |
| C6 | `parrot.stores` uses the same string-dispatch idiom via `supported_stores` | F007 | high | Direct read of `stores/__init__.py:1-10` |
| C7 | `parrot.rerankers` uses module-level `__getattr__` for lazy backend loading | F005 | high | Direct read of `rerankers/__init__.py:30-50` |
| C8 | Embeddings subsystem = 3 concrete backends + 5 base files | F003 | high | Direct tree enumeration |
| C9 | Stores subsystem = 6 concrete top-level backends + 3 sub-packages (kb/parents/utils) + 4 base files | F004 | high | Direct tree enumeration |
| C10 | `parrot.stores.{kb,parents,utils}` stay in core | F004, F012, U2 user decision | high | User decision (Q&A U2) confirmed; higher-level orchestration over AbstractStore; keeps satellite minimal |
| C11 | Rerankers subsystem = 2 concrete backends + 4 base files | F005 | high | Direct tree enumeration |
| C12 | `parrot.stores.models` (Document, SearchResult, etc.) is consumed across rerankers/bots/handlers/manager/knowledge — must stay in core | F012 | high | Direct grep evidence |
| C13 | `faiss-cpu` must remain a core dependency even though `FAISSStore` moves out | F008 | high | Direct read of `pyproject.toml:96-99` + explicit code comment |
| C14 | `pgvector` currently lives inside the `images` extra (line 352), not its own extra | F008 | high | Direct read |
| C15 | All existing sibling packages ship under separate top-levels + `sys.meta_path` redirector | F010, F011 | high | Direct reads across siblings |
| C16 | FEAT-079 spec called for PEP 420 but actual implementation reverted to `parrot_formdesigner.*` — FEAT-201 is the first real exercise of namespace extension | F011 | high | Cross-reference spec vs actual layout |
| C17 | `ai-parrot-tools` is the closest precedent for per-backend-extras shape | F009 | high | Direct read |
| C18 | Satellite uses pure PEP 420 (no `__init__.py` at `parrot/`, `/embeddings/`, `/stores/`, `/rerankers/`); host retains its existing `__init__.py` (with `extend_path`) — backends become reachable through the host-rooted namespace | F001, F003, F005, F007, U3 user decision | high | User decision (Q&A U3) locked the layout; spec must include a verification test that the satellite wheel ships no `__init__.py` at these four levels |
| C19 | All three subsystems have active recent work but no in-flight SDD touches packaging — no collision | F013 | high | git log scan |
| C20 | Three meta-extras (`all`, `all-fast`) need rewrites after the split | F008 | high | Direct read of `pyproject.toml:503-510` |

**Distribution: 20 high, 0 medium, 0 low.**

C10 and C18 were upgraded from medium → high after user resolution in
the proposal-phase Q&A (U2, U3).

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Scope: just embeddings extras, or the whole retrieval stack?** —
  *Resolved*: "move stores, embeddings, rerankers to new package
  ai-parrot-embedding, that is the requirement."
  *Resolves claims*: C1
- [x] **Import-stability strategy: top-level rename (sibling precedent)
  or PEP 420 / namespace extension?** — *Resolved*: "my decision is PEP

…(truncated)…
