---
type: Wiki Overview
title: 'Feature Specification: ai-parrot-embeddings — split stores/embeddings/rerankers
  backends into a new sibling package via PEP 420'
id: doc:sdd-specs-ai-parrot-embeddings-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: All concrete backends for the three retrieval subsystems —
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.embeddings
  rel: mentions
- concept: mod:parrot.embeddings.base
  rel: mentions
- concept: mod:parrot.embeddings.catalog
  rel: mentions
- concept: mod:parrot.embeddings.google
  rel: mentions
- concept: mod:parrot.embeddings.huggingface
  rel: mentions
- concept: mod:parrot.embeddings.matryoshka
  rel: mentions
- concept: mod:parrot.embeddings.openai
  rel: mentions
- concept: mod:parrot.embeddings.registry
  rel: mentions
- concept: mod:parrot.handlers.stores
  rel: mentions
- concept: mod:parrot.registry.routing.store_router
  rel: mentions
- concept: mod:parrot.rerankers
  rel: mentions
- concept: mod:parrot.rerankers.abstract
  rel: mentions
- concept: mod:parrot.rerankers.factory
  rel: mentions
- concept: mod:parrot.rerankers.llm
  rel: mentions
- concept: mod:parrot.rerankers.local
  rel: mentions
- concept: mod:parrot.rerankers.models
  rel: mentions
- concept: mod:parrot.stores
  rel: mentions
- concept: mod:parrot.stores.abstract
  rel: mentions
- concept: mod:parrot.stores.arango
  rel: mentions
- concept: mod:parrot.stores.bigquery
  rel: mentions
- concept: mod:parrot.stores.cache
  rel: mentions
- concept: mod:parrot.stores.empty
  rel: mentions
- concept: mod:parrot.stores.faiss_store
  rel: mentions
- concept: mod:parrot.stores.kb
  rel: mentions
- concept: mod:parrot.stores.kb.store
  rel: mentions
- concept: mod:parrot.stores.milvus
  rel: mentions
- concept: mod:parrot.stores.models
  rel: mentions
- concept: mod:parrot.stores.parents
  rel: mentions
- concept: mod:parrot.stores.parents.abstract
  rel: mentions
- concept: mod:parrot.stores.parents.factory
  rel: mentions
- concept: mod:parrot.stores.pgvector
  rel: mentions
- concept: mod:parrot.stores.postgres
  rel: mentions
- concept: mod:parrot.stores.utils
  rel: mentions
- concept: mod:parrot.stores.utils.chunking
  rel: mentions
- concept: mod:parrot.stores.utils.contextual
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.vectorstoresearch
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: ai-parrot-embeddings — split stores/embeddings/rerankers backends into a new sibling package via PEP 420

**Feature ID**: FEAT-201
**Date**: 2026-05-28
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.0.0
**Proposal**: `sdd/proposals/ai-parrot-embeddings.proposal.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

All concrete backends for the three retrieval subsystems —
`parrot.embeddings.{google,huggingface,openai}`,
`parrot.stores.{postgres,milvus,arango,bigquery,faiss_store,pgvector}`,
and `parrot.rerankers.{local,llm}` — currently live in the
`ai-parrot` core distribution. This means every consumer of the
framework pulls heavy backend dependencies (sentence-transformers,
pymilvus, python-arango-async, google-cloud-bigquery, pgvector, faiss,
chromadb, ML libs like accelerate/peft/xformers) even when they only
need the base agent framework. Earlier work — `ai-parrot-tools`,
`ai-parrot-loaders`, `ai-parrot-pipelines`, `parrot-formdesigner` —
already split tools, loaders, pipelines, and form-design out, but those
shipped under separate top-levels (`parrot_tools.*`, `parrot_loaders.*`,
etc.) bridged via `sys.meta_path` redirectors in core. The retrieval
stack remains unsplit.

The owner has decided FEAT-201 takes a **different** structural
approach than the existing sibling-package precedent: the new package
ships its modules **under the existing `parrot.*` namespace** via
PEP 420 implicit namespace packages, so every existing
`from parrot.stores.pgvector import PgVectorStore` import site stays
**byte-identical** with no `__getattr__` proxy, no `parrot_embeddings.*`
top-level rename, and no `sys.meta_path` finder.

### Goals

1. **One new distributable package**: `ai-parrot-embeddings` under
   `packages/ai-parrot-embeddings/`, with per-backend optional-
   dependencies (`pgvector`, `milvus`, `arango`, `bigquery`, `faiss`,
   `chroma`, `openai`, `google`, `huggingface`, `reranker-local`,
   `reranker-llm`, `all`).
2. **PEP 420 namespace contribution**: the satellite ships **no
   `__init__.py`** at `parrot/`, `parrot/embeddings/`, `parrot/stores/`,
   `parrot/rerankers/` — Python merges its directory contents into the
   host's regular `parrot.{embeddings,stores,rerankers}` packages at
   import time.
3. **Byte-identical import surface**: every existing
   `from parrot.{embeddings,stores,rerankers}.X import Y` site
   continues to work unchanged after the split.
4. **Backend isolation**: `pip install ai-parrot` (core only) installs
   the framework without any backend deps; users opt in via
   `pip install ai-parrot-embeddings[pgvector,milvus]` etc.
5. **No host-pyproject regression**: meta-extras `all` and `all-fast`
   must continue to yield the same functional stack as today, even
   though they now reach across distributions.
6. **`faiss-cpu` stays a core dep**: episodic memory's default backend
   needs it; the FAISS *store* moves but the Python lib stays in core
   dependencies.
7. **`pgvector` extra hygiene**: today it is bundled inside the `images`
   extra (line 352 of host pyproject); FEAT-201 extracts it into its
   proper home (`ai-parrot-embeddings[pgvector]`).

### Non-Goals (explicitly out of scope)

- **Retrofitting** `ai-parrot-tools`, `-loaders`, `-pipelines`, or
  `parrot-formdesigner` to the PEP 420 convention — they keep their
  `parrot_<name>.*` + meta_path redirector machinery. FEAT-201
  introduces a new convention alongside, not a retrofit.
- **Two packages** (`ai-parrot-embeddings` + `ai-parrot-vectorstores`)
  — owner has chosen one package; rejected during proposal phase.
- **`parrot_embeddings.*` top-level** (the sibling-package precedent)
  — owner explicitly chose PEP 420 instead. *Rejected option, see
  `sdd/proposals/ai-parrot-embeddings.proposal.md` §3 and the F010
  finding.*
- **Moving the dispatch tables, registries, abstracts, or shared
  types** (`supported_embeddings`, `supported_stores`,
  `EmbeddingRegistry`, `AbstractEmbeddingModel`, `AbstractStore`,
  `AbstractReranker`, `parrot.stores.models.{Document,SearchResult,
  StoreConfig,DistanceStrategy}`) — they stay in core.
- **Moving the higher-level stores sub-packages** (`parrot.stores.kb`,
  `parrot.stores.parents`, `parrot.stores.utils`) — they stay in core
  per owner decision (U2).
- **Moving the core RAG-primitive tools** (`VectorStoreSearchTool`,
  `MultiStoreSearchTool`) — they stay in core per the FEAT-057
  explicit decision (`sdd/specs/monorepo-migration.spec.md:131-132`).
- **Changing any backend's runtime API** — signatures, return types,
  async semantics all preserved.
- **Removing any backend** — every backend that exists today must
  remain installable somehow after the split.
- **Cython / Rust extensions** — `parrot.yaml_rs` lives in core; FEAT-201
  does not touch it.

---

## 2. Architectural Design

### Overview

Create a new uv-workspace member `ai-parrot-embeddings` under
`packages/ai-parrot-embeddings/`. Its `src/` tree contains **only**
the concrete backend modules at the same dotted-path locations they
occupy today in the host — but **no `__init__.py` files** at the
namespace levels (`parrot/`, `parrot/embeddings/`, `parrot/stores/`,
`parrot/rerankers/`). Python's PEP 420 implicit-namespace-package
mechanism merges the satellite's directory entries with the host's
regular packages at import time. Because the host's `__init__.py`
files at those levels remain unchanged (with `supported_embeddings`,
`supported_stores`, `__getattr__` lazy loaders, etc.), they continue
to govern the public surface of `parrot.{embeddings,stores,rerankers}`.

The host pyproject's existing `[tool.setuptools.packages.find]` block
already declares `namespaces = true` + `include = ["parrot*"]`
(`packages/ai-parrot/pyproject.toml:529-532`); the satellite's pyproject
mirrors that. The root `pyproject.toml` already declares
`[tool.uv.workspace] members = ["packages/*"]` (line 43-44), so the
new package is **auto-discovered** — no root edit needed.

The host pyproject's `embeddings`, `milvus`, `chroma`, `arango`,
`bigquery` extras are removed (their deps move to the new package).
`pgvector==0.4.1` is extracted from the `images` extra. The `all` and
`all-fast` meta-extras are rewritten to pull from
`ai-parrot-embeddings[...]`. `faiss-cpu` stays in core dependencies.

### Component Diagram

```
                                           ┌─ pip install ai-parrot
                                           │     core framework, no backends
                                           │     (still includes faiss-cpu for
                                           │      episodic memory default)
                                           │
                                           └─ pip install ai-parrot-embeddings[pgvector,milvus,reranker-local]
                                                 backends layered on top via PEP 420
                                                 imports continue: from parrot.stores.pgvector import PgVectorStore

┌────────────────────── ai-parrot (host) ──────────────────────┐    ┌──────────── ai-parrot-embeddings (satellite) ────────────┐
│ src/parrot/                                                   │    │ src/parrot/                                                │
│   __init__.py        (extend_path; STAYS)                     │    │   ── NO __init__.py ──                                     │
│   embeddings/                                                 │    │   embeddings/                                              │
│     __init__.py      (supported_embeddings map; STAYS)        │    │     ── NO __init__.py ──                                   │
│     base.py          (EmbeddingModel ABC; STAYS)              │    │     google.py             (GoogleEmbeddingModel)           │
│     registry.py      (EmbeddingRegistry; STAYS)               │    │     huggingface.py        (SentenceTransformerModel)       │
│     catalog.py       (EMBEDDING_MODELS; STAYS)                │    │     openai.py             (OpenAIEmbeddingModel)           │
│     matryoshka.py    (MatryoshkaConfig; STAYS)                │    │   stores/                                                  │
│     processor.py     (STAYS)                                  │    │     ── NO __init__.py ──                                   │
│   stores/                                                     │    │     postgres.py           (PgVectorStore — heavy)          │
│     __init__.py      (supported_stores map; STAYS)            │    │     pgvector.py           (3-line shim of postgres)        │
│     abstract.py      (AbstractStore ABC; STAYS)               │    │     milvus.py             (MilvusStore)                    │
│     models.py        (Document/SearchResult/.../STAYS)        │    │     arango.py             (ArangoDBStore)                  │
│     empty.py / cache.py    (STAY)                             │    │     bigquery.py           (BigQueryStore)                  │
│     kb/ parents/ utils/   (STAY — per U2)                     │    │     faiss_store.py        (FAISSStore)                     │
│   rerankers/                                                  │    │   rerankers/                                               │
│     __init__.py      (lazy __getattr__; STAYS)                │    │     ── NO __init__.py ──                                   │
│     abstract.py      (AbstractReranker ABC; STAYS)            │    │     local.py              (LocalCrossEncoderReranker)      │
│     models.py        (RerankedDocument/RerankerConfig; STAYS) │    │     llm.py                (LLMReranker)                    │
│     factory.py       (create_reranker; STAYS)                 │    │                                                            │
│                                                               │    │ pyproject.toml                                             │
│   tools/                                                      │    │   name = "ai-parrot-embeddings"                            │
│     vectorstoresearch.py    (STAYS — core RAG primitive)      │    │   dependencies = ["ai-parrot"]                             │
│     multistoresearch.py     (STAYS — core RAG primitive)      │    │   [project.optional-dependencies]                          │
│   handlers/stores/         (STAYS — HTTP handlers)            │    │     pgvector / milvus / arango / bigquery / faiss          │
│   registry/routing/        (STAYS — StoreRouter)              │    │     chroma / openai / google / huggingface                 │
│                                                               │    │     reranker-local / reranker-llm / all                    │
│ pyproject.toml                                                │    │   [tool.setuptools.packages.find]                          │
│   embeddings/milvus/chroma/arango/bigquery extras REMOVED     │    │     where = ["src"]                                        │
│   pgvector EXTRACTED from images extra                        │    │     include = ["parrot*"]                                  │
│   all/all-fast meta-extras REWRITTEN                          │    │     namespaces = true                                      │
│   faiss-cpu STAYS in core deps                                │    │   [tool.uv.sources] ai-parrot = { workspace = true }       │
└───────────────────────────────────────────────────────────────┘    └────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.embeddings.EmbeddingRegistry._build_model` | unchanged | Resolves backends by `importlib.import_module(f"parrot.embeddings.{model_type}")` — string-based, satellite-supplied module reachable through merged namespace |
| `parrot.embeddings.supported_embeddings` dict | unchanged | Stays in host's `embeddings/__init__.py` |
| `parrot.stores.supported_stores` dict | unchanged | Stays in host's `stores/__init__.py` |
| `parrot.stores.abstract.AbstractStore` | unchanged | Concrete satellite backends `import` it (cross-distribution import works under namespace merging) |
| `parrot.stores.models.{Document,SearchResult,StoreConfig,DistanceStrategy}` | unchanged | Shared types — satellite backends `from parrot.stores.models import ...` |
| `parrot.rerankers.__init__.py` `__getattr__` | unchanged | Lazy import of `local` / `llm` resolves through merged namespace |
| `parrot.rerankers.factory.create_reranker` | unchanged | Local imports of `parrot.rerankers.local` / `.llm` resolve through merged namespace |
| `parrot.handlers.stores` | unchanged | HTTP handlers continue to `from parrot.stores import supported_stores, AbstractStore` |
| `parrot.registry.routing.store_router` | unchanged | `from parrot.stores.abstract import AbstractStore` continues to resolve |
| `parrot.tools.{vectorstoresearch,multistoresearch}` | unchanged | Stay in core (FEAT-057 decision) |
| Root `pyproject.toml` `[tool.uv.workspace]` | none | `members = ["packages/*"]` auto-includes the new package |
| Host `pyproject.toml` extras | replaced / migrated | See Module 5 |

### Data Models

No new Pydantic models. The split is purely a packaging boundary; all
existing data models stay in core unchanged:

- `parrot.stores.models.Document` (line 40)
- `parrot.stores.models.SearchResult` (line 7)
- `parrot.stores.models.DistanceStrategy` (line 49)
- `parrot.stores.models.StoreConfig` (line 61)
- `parrot.rerankers.models.RerankedDocument` / `RerankerConfig`
- `parrot.embeddings.matryoshka.MatryoshkaConfig`

### New Public Interfaces

None at runtime — all moved classes keep their existing public names
and import paths. The only public-surface change is the **install
surface**:

```bash
# After FEAT-201:
pip install ai-parrot                          # core, no backends (still faiss-cpu)
pip install ai-parrot-embeddings[pgvector]     # + PgVectorStore
pip install ai-parrot-embeddings[milvus,faiss] # + MilvusStore, FAISSStore
pip install ai-parrot-embeddings[huggingface]  # + SentenceTransformerModel
pip install ai-parrot-embeddings[reranker-local] # + LocalCrossEncoderReranker
pip install ai-parrot-embeddings[all]          # everything
```

The host's `all` and `all-fast` meta-extras are rewritten so the
legacy one-liner still works:

```bash
pip install ai-parrot[all]      # ⇒ ai-parrot + ai-parrot-embeddings[all] + ...
pip install ai-parrot[all-fast] # ⇒ ai-parrot + ai-parrot-embeddings[huggingface,faiss,pgvector]
```

---

## 3. Module Breakdown

### Module 1: New package scaffold

- **Path**:
  - `packages/ai-parrot-embeddings/pyproject.toml`
  - `packages/ai-parrot-embeddings/README.md`
  - `packages/ai-parrot-embeddings/src/parrot/` (directory only; **no
    `__init__.py`**)
  - `packages/ai-parrot-embeddings/src/parrot/embeddings/` (directory
    only; **no `__init__.py`**)
  - `packages/ai-parrot-embeddings/src/parrot/stores/` (directory only;
    **no `__init__.py`**)
  - `packages/ai-parrot-embeddings/src/parrot/rerankers/` (directory
    only; **no `__init__.py`**)
  - `packages/ai-parrot-embeddings/tests/` (test root)
- **Responsibility**: scaffold the empty satellite package — pyproject
  with `name = "ai-parrot-embeddings"`, `dependencies = ["ai-parrot"]`,
  `[tool.setuptools.packages.find]` with
  `where = ["src"]`, `include = ["parrot*"]`, `namespaces = true`,
  `[tool.uv.sources] ai-parrot = { workspace = true }`. Verify
  `uv sync --all-packages` installs the empty package in editable mode
  alongside `ai-parrot` without error. Verify the satellite wheel
  contains **no** `__init__.py` at any of the four levels.
- **Depends on**: none (workspace already configured at root).

### Module 2: Embedding backends migration

- **Path** (in the satellite, after move):
  - `packages/ai-parrot-embeddings/src/parrot/embeddings/google.py`
  - `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py`
  - `packages/ai-parrot-embeddings/src/parrot/embeddings/openai.py`
- **Responsibility**: `git mv` (preserving history) the three
  concrete embedding backends from the host to the satellite. Add
  per-backend extras to the satellite pyproject: `google`,
  `huggingface`, `openai`. Existing internal imports stay
  byte-identical (e.g. `from parrot.embeddings.base import
  EmbeddingModel`, `from parrot.embeddings.matryoshka import
  MatryoshkaConfig` — both stay in core under merged namespace).
- **Depends on**: Module 1.

### Module 3: Store backends migration

- **Path** (in the satellite, after move):
  - `packages/ai-parrot-embeddings/src/parrot/stores/postgres.py`
  - `packages/ai-parrot-embeddings/src/parrot/stores/pgvector.py`
    (3-line shim re-exporting from postgres — moves with it)
  - `packages/ai-parrot-embeddings/src/parrot/stores/faiss_store.py`
  - `packages/ai-parrot-embeddings/src/parrot/stores/milvus.py`
  - `packages/ai-parrot-embeddings/src/parrot/stores/arango.py`
  - `packages/ai-parrot-embeddings/src/parrot/stores/bigquery.py`
- **Responsibility**: `git mv` the six concrete vector-store backends.
  Add per-backend extras to the satellite pyproject:
  `pgvector`, `milvus`, `arango`, `bigquery`, `faiss`, `chroma`.
  Internal imports preserved (e.g.
  `from parrot.stores.abstract import AbstractStore`,
  `from parrot.stores.models import Document, SearchResult` — stay
  in core).
- **Depends on**: Module 1.

> **Boundary clarification**: the higher-level sub-packages
> `parrot.stores.kb`, `parrot.stores.parents`, `parrot.stores.utils`,
> plus `parrot.stores.empty`, `parrot.stores.cache`, **STAY in core**
> per resolved question U2. Only the six backend files at the top
> level of `parrot/stores/` move.

### Module 4: Reranker backends migration

- **Path** (in the satellite, after move):
  - `packages/ai-parrot-embeddings/src/parrot/rerankers/local.py`
  - `packages/ai-parrot-embeddings/src/parrot/rerankers/llm.py`
- **Responsibility**: `git mv` the two concrete rerankers. Add
  `reranker-local` and `reranker-llm` extras to the satellite
  pyproject. The host's `parrot.rerankers.__init__.py` module-level
  `__getattr__` already does the lazy resolution and continues to work
  unchanged under merged namespace.
- **Depends on**: Module 1.

### Module 5: Host pyproject extras redistribution

- **Path**: `packages/ai-parrot/pyproject.toml`
- **Responsibility**:
  - Remove the `embeddings` extra block (lines 287-308 of current host
    pyproject) — its deps move to `ai-parrot-embeddings[huggingface]`
    + `[faiss]` + `[chroma]` etc.
  - Remove the `milvus` extra (lines 408-411).
  - Remove the `chroma` extra (lines 413-415).
  - Remove the `bigquery` extra (lines 124-126), unless the asyncdb
    bigquery extra still needs the google-cloud-bigquery dep —
    confirm in implementation.
  - Remove the `arango` extra (lines 172-174).
  - Extract `pgvector==0.4.1` from the `images` extra (line 352).
  - Rewrite `all` (line 505) to:
    `"ai-parrot[agents,images,llms,integrations,db,bigquery,pdf,ocr,
    audio,finance,flowtask,scheduler,reddit,mcp,charts,docling]"` plus
    `"ai-parrot-embeddings[all]"`.
  - Rewrite `all-fast` (line 509) to:
    `"ai-parrot[agents-lite,llms,integrations]"` plus
    `"ai-parrot-embeddings[huggingface,faiss,pgvector]"`.
  - **Keep `faiss-cpu>=1.9.0` in core dependencies** (line 98). Do not
    move it to an extra. (Episodic memory needs it as default.)
- **Depends on**: Modules 2, 3, 4 (the per-backend extras in the
  satellite must exist before host pyproject references them).

### Module 6: Satellite wheel-content verification test

- **Path**:
  `packages/ai-parrot-embeddings/tests/test_wheel_layout.py`
- **Responsibility**: a pytest that builds the satellite wheel with
  `python -m build --wheel` (or `uv build`), then opens the resulting
  `.whl` zip and asserts there is **no** `__init__.py` file at any of
  these four paths inside the wheel:
  - `parrot/__init__.py`
  - `parrot/embeddings/__init__.py`
  - `parrot/stores/__init__.py`
  - `parrot/rerankers/__init__.py`
  This locks the U3 (pure PEP 420) decision into CI. The test should
  also assert presence of the expected backend `.py` files.
- **Depends on**: Modules 2, 3, 4.

### Module 7: Cross-distribution namespace-resolution test suite

- **Path**:
  `packages/ai-parrot-embeddings/tests/test_namespace_imports.py`
- **Responsibility**: integration tests that exercise the namespace
  merging:
  - With `ai-parrot-embeddings` installed: assert
    `from parrot.stores.pgvector import PgVectorStore` works,
    `from parrot.embeddings.huggingface import SentenceTransformerModel`
    works, `from parrot.rerankers.local import
    LocalCrossEncoderReranker` works, **and** the resulting modules'
    `__file__` attribute points inside the satellite distribution (not
    inside `ai-parrot`).
  - With the satellite **not** installed (simulated by removing the
    satellite from `sys.modules` and patching the import path):
    confirm `from parrot.stores.pgvector import PgVectorStore` raises
    a clear, actionable `ImportError` (one that tells the user to
    `pip install ai-parrot-embeddings[pgvector]`).
  - Confirm the host's `supported_stores` and `supported_embeddings`
    dispatch maps still load and contain the expected keys regardless
    of satellite presence.
- **Depends on**: Modules 2, 3, 4.

### Module 8: Matryoshka + contextual-augmentation regression suite

- **Path**: keep existing tests where they are; add a smoke test at
  `packages/ai-parrot-embeddings/tests/test_cross_dist_matryoshka.py`
  that runs the Matryoshka happy path
  (`SentenceTransformerModel.encode(...)` with `matryoshka` kwarg) and
  the contextual-augmentation happy path
  (`AbstractStore.create_embedding` forwarding `matryoshka` kwarg
  through to satellite-supplied stores) in an environment where the
  satellite is installed.
- **Responsibility**: prove that FEAT-150 (matryoshka truncation) and
  FEAT-127/128 (contextual embedding) wirings — which cross the
  core ↔ satellite boundary — continue to function after the move.
- **Depends on**: Modules 2, 3.

### Module 9: Documentation + migration notes

- **Path**:
  - `packages/ai-parrot-embeddings/README.md`
  - `docs/migration/feat-201-ai-parrot-embeddings.md`
  - Update `.agent/CONTEXT.md` "What Lives Where" section if it lists
    `embeddings/` / `stores/` / `rerankers/` as core (it does — at the
    top of `.agent/CONTEXT.md` "What Lives Where").
- **Responsibility**: write the satellite README (install patterns,
  extras list, relationship to `ai-parrot`); write a one-page
  migration doc capturing the install-surface changes for existing
  users (`pip install ai-parrot[embeddings]` → `pip install
  ai-parrot-embeddings[huggingface,faiss,pgvector,...]`); update
  `.agent/CONTEXT.md` to reflect that backend implementations may live
  in either ai-parrot or ai-parrot-embeddings (the import path is
  unchanged either way).
- **Depends on**: Modules 5, 6, 7 (after the install surface is
  finalized and verified).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_satellite_pyproject_valid` | 1 | `uv build` of the satellite succeeds; pyproject parses; per-backend extras resolve |
| `test_satellite_wheel_no_init_at_namespace_levels` | 6 | Wheel contains NO `__init__.py` at `parrot/`, `parrot/embeddings/`, `parrot/stores/`, `parrot/rerankers/` |
| `test_satellite_wheel_contains_expected_backends` | 6 | Wheel contains `google.py`, `huggingface.py`, `openai.py` under `parrot/embeddings/` and corresponding files under `stores/` and `rerankers/` |
| `test_host_pyproject_no_moved_extras` | 5 | Host pyproject no longer has `[project.optional-dependencies]` blocks named `embeddings`, `milvus`, `chroma`, `arango` |
| `test_host_images_extra_no_pgvector` | 5 | The host `images` extra no longer contains `pgvector` |

…(truncated)…
