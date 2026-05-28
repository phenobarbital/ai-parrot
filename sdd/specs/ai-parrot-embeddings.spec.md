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
| `test_host_faiss_cpu_in_core_deps` | 5 | `faiss-cpu>=1.9.0` remains a top-level entry in host `[project] dependencies` |
| `test_host_all_meta_extra_includes_satellite` | 5 | Host `all` meta-extra string contains `ai-parrot-embeddings[all]` |
| `test_host_all_fast_meta_extra_includes_satellite` | 5 | Host `all-fast` meta-extra string contains `ai-parrot-embeddings[...]` |
| `test_supported_embeddings_dispatch_keys_unchanged` | 2 | After move, `parrot.embeddings.supported_embeddings` still contains keys `huggingface`, `google`, `openai` |
| `test_supported_stores_dispatch_keys_unchanged` | 3 | After move, `parrot.stores.supported_stores` still contains keys `postgres`, `milvus`, `kb`, `faiss_store`, `arango`, `bigquery` |
| `test_rerankers_lazy_getattr_unchanged` | 4 | `parrot.rerankers.LocalCrossEncoderReranker` and `parrot.rerankers.LLMReranker` still resolve through the host's `__getattr__` |
| `test_pgvector_shim_still_reexports` | 3 | `parrot.stores.pgvector.PgVectorStore is parrot.stores.postgres.PgVectorStore` |

### Integration Tests

| Test | Description |
|---|---|
| `test_imports_with_satellite_installed` (Module 7) | All of `from parrot.embeddings.huggingface import SentenceTransformerModel`, `from parrot.stores.pgvector import PgVectorStore`, `from parrot.stores.milvus import MilvusStore`, `from parrot.stores.arango import ArangoDBStore`, `from parrot.stores.bigquery import BigQueryStore`, `from parrot.stores.faiss_store import FAISSStore`, `from parrot.rerankers.local import LocalCrossEncoderReranker`, `from parrot.rerankers.llm import LLMReranker` succeed |
| `test_modules_resolve_to_satellite` (Module 7) | For each moved backend, `module.__file__` resolves inside `ai-parrot-embeddings` distribution, NOT `ai-parrot` |
| `test_imports_without_satellite_raise_clear_error` (Module 7) | In a clean venv with only `ai-parrot` installed, `from parrot.stores.pgvector import PgVectorStore` raises `ImportError` with install-instruction text mentioning `ai-parrot-embeddings[pgvector]` |
| `test_registry_resolves_backend_after_move` (Module 2) | `EmbeddingRegistry.instance().get_or_create_sync("all-MiniLM-L6-v2", "huggingface")` succeeds with the satellite installed (string-dispatch path works across distributions) |
| `test_matryoshka_cross_distribution` (Module 8) | Matryoshka kwarg-forwarding chain works end-to-end across the boundary (`AbstractStore.create_embedding(matryoshka={...})` → `SentenceTransformerModel.encode(matryoshka=...)`) |
| `test_contextual_augmentation_cross_distribution` (Module 8) | `AbstractStore._apply_contextual_augmentation` hook still fires when stores live in the satellite |
| `test_pip_install_ai_parrot_alone` (Module 9 / CI) | Clean venv: `pip install ai-parrot` succeeds; `import parrot` succeeds; `from parrot.stores import AbstractStore, supported_stores` succeeds; importing a satellite-only backend raises the expected ImportError |
| `test_pip_install_ai_parrot_embeddings_all` (Module 9 / CI) | Clean venv: `pip install ai-parrot ai-parrot-embeddings[all]` succeeds; all backends importable |
| `test_pip_install_ai_parrot_all_meta_extra` (Module 9 / CI) | Clean venv: `pip install ai-parrot[all]` resolves the satellite via the rewritten meta-extra; full backend stack present |
| `test_uv_sync_all_packages` (Module 1 / CI) | `uv sync --all-packages` from repo root installs both ai-parrot and ai-parrot-embeddings in editable mode without conflict |

### Test Data / Fixtures

```python
# packages/ai-parrot-embeddings/tests/conftest.py
import sys
import zipfile
from pathlib import Path
import pytest


@pytest.fixture(scope="session")
def satellite_wheel_path(tmp_path_factory) -> Path:
    """Build the satellite wheel once per test session and return its path."""
    import subprocess
    out_dir = tmp_path_factory.mktemp("wheel")
    subprocess.check_call(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
        cwd=Path(__file__).parent.parent,  # the satellite package root
    )
    wheels = list(out_dir.glob("ai_parrot_embeddings-*.whl"))
    assert len(wheels) == 1, f"expected 1 wheel, found {wheels}"
    return wheels[0]


@pytest.fixture
def satellite_wheel_namelist(satellite_wheel_path) -> list[str]:
    """Names of all files inside the satellite wheel."""
    with zipfile.ZipFile(satellite_wheel_path) as zf:
        return zf.namelist()


@pytest.fixture
def host_pyproject_text() -> str:
    """The host's current pyproject.toml text."""
    return Path("packages/ai-parrot/pyproject.toml").read_text(encoding="utf-8")
```

---

## 5. Acceptance Criteria

This feature is complete when **ALL** of the following are true:

- [ ] `packages/ai-parrot-embeddings/` exists with `pyproject.toml`, `README.md`,
      `src/parrot/{embeddings,stores,rerankers}/` directory trees, and a `tests/` root.
- [ ] **Satellite wheel contains NO `__init__.py`** at any of the four
      namespace levels (`parrot/`, `parrot/embeddings/`,
      `parrot/stores/`, `parrot/rerankers/`). Verified by
      `test_satellite_wheel_no_init_at_namespace_levels`.
- [ ] The new satellite pyproject declares per-backend extras
      `pgvector`, `milvus`, `arango`, `bigquery`, `faiss`, `chroma`,
      `openai`, `google`, `huggingface`, `reranker-local`,
      `reranker-llm`, and an `all` aggregator.
- [ ] `uv sync --all-packages` from repo root installs both
      `ai-parrot` and `ai-parrot-embeddings` in editable mode without
      conflict.
- [ ] After move, the following files no longer exist in the host
      package:
      `packages/ai-parrot/src/parrot/embeddings/{google,huggingface,openai}.py`,
      `packages/ai-parrot/src/parrot/stores/{postgres,pgvector,faiss_store,milvus,arango,bigquery}.py`,
      `packages/ai-parrot/src/parrot/rerankers/{local,llm}.py`.
- [ ] After move, these files exist in the satellite at the equivalent
      paths under `packages/ai-parrot-embeddings/src/parrot/{...}/`.
- [ ] **All existing `from parrot.{embeddings,stores,rerankers}.X import Y`
      sites continue to work byte-identically** with the satellite installed.
      Verified by `test_imports_with_satellite_installed` and by running
      the existing core test suite green.
- [ ] **Without the satellite installed**, importing a moved backend
      raises a clear `ImportError` whose message tells the user to
      `pip install ai-parrot-embeddings[<extra>]`. Verified by
      `test_imports_without_satellite_raise_clear_error`.
- [ ] `parrot.embeddings.supported_embeddings` and
      `parrot.stores.supported_stores` dispatch maps **stay in core** and
      remain byte-identical (same keys, same values).
- [ ] `parrot.embeddings.EmbeddingRegistry`,
      `parrot.embeddings.base.EmbeddingModel`,
      `parrot.stores.abstract.AbstractStore`,
      `parrot.stores.models.{Document,SearchResult,StoreConfig,DistanceStrategy}`,
      `parrot.rerankers.abstract.AbstractReranker`, and
      `parrot.rerankers.{factory,models}` **stay in core** unchanged.
- [ ] Host `pyproject.toml` no longer declares the `embeddings`,
      `milvus`, `chroma`, `arango` extras. (`bigquery` may stay if the
      asyncdb dep still needs it — confirmed at implementation.)
- [ ] Host `pyproject.toml` `images` extra no longer contains
      `pgvector==0.4.1`.
- [ ] Host `pyproject.toml` keeps `faiss-cpu>=1.9.0` in core
      dependencies (line ~98 today).
- [ ] Host `pyproject.toml` `all` and `all-fast` meta-extras reference
      `ai-parrot-embeddings[...]` so that `pip install ai-parrot[all]`
      yields the same backend stack as today.
- [ ] Matryoshka kwarg-forwarding (FEAT-150) works across the boundary:
      `test_matryoshka_cross_distribution` green.
- [ ] Contextual-augmentation wiring (FEAT-127/128) works across the
      boundary: `test_contextual_augmentation_cross_distribution` green.
- [ ] `parrot.stores.kb`, `parrot.stores.parents`, `parrot.stores.utils`,
      `parrot.stores.empty`, `parrot.stores.cache` **stay in core**
      (per U2).
- [ ] `parrot.tools.vectorstoresearch` and
      `parrot.tools.multistoresearch` **stay in core** (per FEAT-057).
- [ ] `parrot.handlers.stores` HTTP handlers continue to operate
      unchanged.
- [ ] Existing sibling packages (`ai-parrot-tools`, `-loaders`,
      `-pipelines`, `parrot-formdesigner`) are **not touched**.
- [ ] Satellite `README.md` documents install patterns + extras list.
- [ ] Migration doc at `docs/migration/feat-201-ai-parrot-embeddings.md`
      summarizes user-visible changes (extras renames, meta-extra
      rewrite).
- [ ] `.agent/CONTEXT.md` "What Lives Where" section updated to reflect
      that backends may live in either distribution but import paths are
      unchanged.
- [ ] Full core test suite (`pytest packages/ai-parrot/tests/`) passes
      after the move with the satellite installed.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This is the single source of truth for what exists in the codebase as of
> 2026-05-28. Every reference below was verified against the actual files
> during the FEAT-201 proposal phase (see findings F001-F014 at
> `sdd/state/FEAT-201/findings/`). Implementation agents MUST NOT
> reference imports, attributes, or methods not listed here without first
> verifying them via `grep` or `read`.

### Verified Imports (stay in core after FEAT-201)

```python
# Embeddings — base / Registry / dispatch (STAY in core)
from parrot.embeddings import EmbeddingRegistry             # verified: packages/ai-parrot/src/parrot/embeddings/__init__.py:1
from parrot.embeddings import supported_embeddings          # verified: packages/ai-parrot/src/parrot/embeddings/__init__.py:14
from parrot.embeddings.registry import EmbeddingRegistry    # verified: packages/ai-parrot/src/parrot/embeddings/registry.py:51
from parrot.embeddings.base import EmbeddingModel           # verified: packages/ai-parrot/src/parrot/embeddings/base.py:15
from parrot.embeddings.catalog import (                     # verified: packages/ai-parrot/src/parrot/embeddings/__init__.py:2-8
    EMBEDDING_MODELS,
    USE_CASE_DESCRIPTIONS,
    get_embedding_models,
    get_model_recommendations,
    get_use_cases,
)
from parrot.embeddings.matryoshka import (                  # verified: packages/ai-parrot/src/parrot/embeddings/__init__.py:9
    MatryoshkaConfig,
    validate_against_catalog,
)

# Stores — base / dispatch / shared types (STAY in core)
from parrot.stores import AbstractStore                     # verified: packages/ai-parrot/src/parrot/stores/__init__.py:1
from parrot.stores import supported_stores                  # verified: packages/ai-parrot/src/parrot/stores/__init__.py:3
from parrot.stores.abstract import AbstractStore            # verified: packages/ai-parrot/src/parrot/stores/abstract.py:60
from parrot.stores.models import (                          # verified: packages/ai-parrot/src/parrot/stores/models.py
    SearchResult,       # line 7
    Document,           # line 40
    DistanceStrategy,   # line 49
    StoreConfig,        # line 61
)

# Stores — higher-level sub-packages (STAY in core, per U2)
from parrot.stores.kb.store import KnowledgeBaseStore       # exists at packages/ai-parrot/src/parrot/stores/kb/store.py
from parrot.stores.parents.abstract import AbstractParentSearcher  # exists at .../stores/parents/abstract.py
from parrot.stores.parents.factory import create_parent_searcher   # exists at .../stores/parents/factory.py
from parrot.stores.utils.chunking import *                  # exists at .../stores/utils/chunking.py
from parrot.stores.utils.contextual import *                # exists at .../stores/utils/contextual.py

# Rerankers — base / factory / dispatch (STAY in core)
from parrot.rerankers import AbstractReranker               # verified: packages/ai-parrot/src/parrot/rerankers/__init__.py:26
from parrot.rerankers import RerankedDocument, RerankerConfig  # verified: packages/ai-parrot/src/parrot/rerankers/__init__.py:27
from parrot.rerankers.abstract import AbstractReranker      # verified: packages/ai-parrot/src/parrot/rerankers/abstract.py:35
from parrot.rerankers.factory import create_reranker        # verified: packages/ai-parrot/src/parrot/rerankers/factory.py:26-83

# Lazy via __getattr__ (STAY working — resolve via merged namespace)
from parrot.rerankers import LocalCrossEncoderReranker      # verified: packages/ai-parrot/src/parrot/rerankers/__init__.py:42-45 (lazy)
from parrot.rerankers import LLMReranker                    # verified: packages/ai-parrot/src/parrot/rerankers/__init__.py:46-49 (lazy)
```

### Verified Imports (MOVE to ai-parrot-embeddings; **import path unchanged**)

```python
# Embedding backends (move; same import path after install)
from parrot.embeddings.huggingface import SentenceTransformerModel  # verified existence
from parrot.embeddings.google import GoogleEmbeddingModel           # verified existence
from parrot.embeddings.openai import OpenAIEmbeddingModel           # verified existence

# Vector-store backends (move; same import path after install)
from parrot.stores.postgres import PgVectorStore     # verified: packages/ai-parrot/src/parrot/stores/postgres.py:49
from parrot.stores.pgvector import PgVectorStore     # verified: packages/ai-parrot/src/parrot/stores/pgvector.py:1 (3-line shim)
from parrot.stores.milvus import MilvusStore         # verified: packages/ai-parrot/src/parrot/stores/milvus.py:67
from parrot.stores.arango import ArangoDBStore       # verified: packages/ai-parrot/src/parrot/stores/arango.py:28
from parrot.stores.bigquery import BigQueryStore     # verified: packages/ai-parrot/src/parrot/stores/bigquery.py:23
from parrot.stores.faiss_store import FAISSStore     # verified: packages/ai-parrot/src/parrot/stores/faiss_store.py:32

# Rerankers (move; same import path after install)
from parrot.rerankers.local import LocalCrossEncoderReranker  # verified existence
from parrot.rerankers.llm import LLMReranker                  # verified existence
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/embeddings/registry.py
class EmbeddingRegistry:                                            # line 51
    _instance: Optional["EmbeddingRegistry"] = None                 # line 71
    _instance_lock: threading.Lock = threading.Lock()               # line 72

    def __init__(self, max_models: int = None) -> None:             # line 74
        # Imports `supported_embeddings` from parrot.embeddings.__init__
        # and `EMBEDDING_REGISTRY_MAX_MODELS` from parrot.conf.

    @classmethod
    def instance(cls, max_models: int = None) -> "EmbeddingRegistry":  # line 100

    def _build_model(self, model_name: str, model_type: str, **kwargs) -> Any:  # line 149
        # String dispatch: importlib.import_module(f"parrot.embeddings.{model_type}")
        # — this resolves through merged namespace after the split.

    async def get_or_create(self, model_name, model_type="huggingface", **kwargs) -> Any:  # line 218
    def get_or_create_sync(self, model_name, model_type="huggingface", **kwargs) -> Any:   # line 345
    async def preload(self, models: List[Dict[str, str]]) -> None:  # line 283
    async def unload(self, model_name, model_type="huggingface") -> bool:  # line 301
    def loaded_models(self) -> List[CacheKey]:                      # line 402
    def stats(self) -> RegistryStats:                               # line 410
    def clear(self) -> None:                                        # line 434


# packages/ai-parrot/src/parrot/embeddings/base.py
class EmbeddingModel(ABC):                                          # line 15
    def __init__(self, model_name: str, **kwargs):                  # line 20

    @abstractmethod
    def _create_embedding(self, model_name: str, **kwargs) -> Any:  # line 162

    @abstractmethod
    async def encode(self, texts: List[str], **kwargs) -> np.ndarray:  # line 226

    async def initialize_model(self) -> None:                       # line 136
    async def embed_documents(self, texts, batch_size=None) -> List[List[float]]:  # line 169
    async def embed_query(self, text, as_nparray=False) -> Union[List[float], List[np.ndarray]]:  # line 188
    def free(self) -> None:                                         # line 216


# packages/ai-parrot/src/parrot/stores/abstract.py
class AbstractStore(ABC):                                           # line 60
    def __init__(self, ...) -> None:                                # line 75
    async def similarity_search(...) -> List[SearchResult]:         # line 216
    async def from_documents(...) -> "AbstractStore":               # line 247
    async def add_documents(...) -> None:                           # line 279
    def create_embedding(self, ..., matryoshka=None) -> EmbeddingModel:  # line 297  (FEAT-150 kwarg)
    async def delete_documents(...) -> None:                        # line 465
    async def delete_documents_by_filter(...) -> None:              # line 491


# packages/ai-parrot/src/parrot/stores/models.py
class SearchResult(BaseModel):    # line 7
class Document(BaseModel):        # line 40
class DistanceStrategy(str, Enum): # line 49 (values: COSINE, EUCLIDEAN, DOT_PRODUCT, etc. — see file)
class StoreConfig:                # line 61 (dataclass — see file)


# packages/ai-parrot/src/parrot/rerankers/abstract.py
class AbstractReranker(ABC):                                        # line 35
    async def rerank(self, query, documents, ...) -> List[RerankedDocument]:  # line 50
    async def load(self) -> None:                                   # line 74
    async def cleanup(self) -> None:                                # line 82


# packages/ai-parrot/src/parrot/embeddings/__init__.py:14-18
supported_embeddings = {
    'huggingface': 'SentenceTransformerModel',
    'google': 'GoogleEmbeddingModel',
    'openai': 'OpenAIEmbeddingModel',
}

# packages/ai-parrot/src/parrot/stores/__init__.py:3-10
supported_stores = {
    'postgres': 'PgVectorStore',
    'milvus': 'MilvusStore',
    'kb': 'KnowledgeBaseStore',
    'faiss_store': 'FaissStore',  # NOTE: dict value is "FaissStore" but class is "FAISSStore" — see Does NOT Exist
    'arango': 'ArangoStore',      # NOTE: dict value is "ArangoStore" but class is "ArangoDBStore" — see Does NOT Exist
    'bigquery': 'BigQueryStore',
}
```

### Integration Points

| New / Moved Component | Connects To | Via | Verified At |
|---|---|---|---|
| Satellite `parrot/embeddings/huggingface.py` | `parrot.embeddings.base.EmbeddingModel` | `from parrot.embeddings.base import EmbeddingModel` (cross-distribution import) | `packages/ai-parrot/src/parrot/embeddings/base.py:15` |
| Satellite `parrot/embeddings/{google,huggingface,openai}.py` | `parrot.embeddings.matryoshka.MatryoshkaConfig` | local imports | `packages/ai-parrot/src/parrot/embeddings/matryoshka.py:10,32` |
| Satellite `parrot/stores/{postgres,milvus,arango,bigquery,faiss_store}.py` | `parrot.stores.abstract.AbstractStore` | `from parrot.stores.abstract import AbstractStore` | `packages/ai-parrot/src/parrot/stores/abstract.py:60` |
| Satellite `parrot/stores/...py` | `parrot.stores.models.{Document,SearchResult,StoreConfig,DistanceStrategy}` | `from parrot.stores.models import ...` | `packages/ai-parrot/src/parrot/stores/models.py:7,40,49,61` |
| Satellite `parrot/stores/pgvector.py` (shim) | `parrot/stores/postgres.PgVectorStore` | `from .postgres import PgVectorStore` (single-line relative import; works after move) | `packages/ai-parrot/src/parrot/stores/pgvector.py:1` |
| Satellite `parrot/rerankers/local.py` | `parrot.rerankers.abstract.AbstractReranker` + `parrot.rerankers.models.RerankerConfig` + `parrot.stores.models.SearchResult` | `from parrot.rerankers.... import ...` and `from parrot.stores.models import SearchResult` | `packages/ai-parrot/src/parrot/rerankers/local.py:40-42` |
| Satellite `parrot/rerankers/llm.py` | `parrot.rerankers.abstract.AbstractReranker` + `parrot.rerankers.models.RerankedDocument` + `parrot.stores.models.SearchResult` | `from parrot.rerankers.... import ...` and `from parrot.stores.models import SearchResult` | `packages/ai-parrot/src/parrot/rerankers/llm.py:29-31` |
| Host `EmbeddingRegistry._build_model` (unchanged) | satellite-supplied backend class | `importlib.import_module(f"parrot.embeddings.{model_type}")` then `getattr(module, cls_name)` | `packages/ai-parrot/src/parrot/embeddings/registry.py:149-178` |
| Host `parrot.rerankers.__init__` (unchanged) | satellite-supplied `LocalCrossEncoderReranker` / `LLMReranker` | module-level `__getattr__` → lazy `from parrot.rerankers.local import ...` | `packages/ai-parrot/src/parrot/rerankers/__init__.py:30-50` |
| Host `parrot.rerankers.factory.create_reranker` (unchanged) | satellite-supplied rerankers | local imports inside `create_reranker` | `packages/ai-parrot/src/parrot/rerankers/factory.py:54,83` |
| Host `parrot.handlers.stores.{handler,helpers}` (unchanged) | host's `supported_stores`, `AbstractStore`, `supported_embeddings` (all stay in core) | imports unchanged | `packages/ai-parrot/src/parrot/handlers/stores/handler.py:17-18`, `helpers.py:4-6` |
| Host `parrot.registry.routing.store_router` (unchanged) | host's `AbstractStore` + `MultiStoreSearchTool.StoreType` (all stay in core) | imports unchanged | `packages/ai-parrot/src/parrot/registry/routing/store_router.py:32-33` |
| Root `pyproject.toml` | new package | auto-discovery via `[tool.uv.workspace] members = ["packages/*"]` — **no edit needed** | `pyproject.toml:43-44` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.stores.FaissStore`~~ — the `supported_stores` dict value is the
  literal string `"FaissStore"` (see `packages/ai-parrot/src/parrot/stores/__init__.py:7`),
  but the **actual class name** is `FAISSStore` (caps-S),
  defined at `packages/ai-parrot/src/parrot/stores/faiss_store.py:32`.
  This is a pre-existing mismatch in the dispatch table — FEAT-201 must NOT
  "fix" it as part of the packaging refactor (out of scope). Implementation
  agents must use `FAISSStore` (caps) when importing directly, and rely on
  whatever lookup logic already handles the dispatch-table value-vs-classname
  mismatch (e.g. `getattr(module, supported_stores[key])`).
- ~~`parrot.stores.ArangoStore`~~ — `supported_stores['arango']` is the literal
  string `"ArangoStore"` (`stores/__init__.py:8`), but the actual class is
  `ArangoDBStore` at `packages/ai-parrot/src/parrot/stores/arango.py:28`.
  Same pre-existing mismatch; same out-of-scope handling.
- ~~`parrot_embeddings.*`~~ — there is **no** top-level package by this name.
  Unlike `ai-parrot-tools` / `-loaders` / `-pipelines` /
  `parrot-formdesigner`, FEAT-201's satellite ships modules under the
  existing `parrot.*` namespace, NOT under a new top-level. Anyone writing
  `import parrot_embeddings` is hallucinating; the correct import is
  `from parrot.embeddings.huggingface import SentenceTransformerModel`
  etc.
- ~~`sys.meta_path` redirector for embeddings~~ — there is NO
  `_ParrotEmbeddingsRedirector` and there must not be one. The existing
  precedent (`_ParrotToolsRedirector` at
  `packages/ai-parrot/src/parrot/tools/__init__.py:50-65`,
  `_ParrotLoadersRedirector` at
  `packages/ai-parrot/src/parrot/loaders/__init__.py`) is **not** the
  pattern for FEAT-201.
- ~~`parrot/embeddings/__init__.py` in satellite~~ — does not exist; must
  not be created. Same for `parrot/__init__.py`, `parrot/stores/__init__.py`,
  `parrot/rerankers/__init__.py` in the satellite (per U3).
- ~~`pgvector` extra in current host pyproject~~ — does NOT exist as a
  standalone extra today. The `pgvector==0.4.1` dependency is buried
  inside the `images` extra at line 352 (per F008). FEAT-201 creates the
  standalone extra (in the **satellite** pyproject, not the host).
- ~~`reranker-local` / `reranker-llm` extras in current host pyproject~~ —
  do NOT exist today. Reranker deps currently piggy-back on `embeddings`
  / `agents`. FEAT-201 creates them as net-new extras (in the satellite).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **uv-workspace + setuptools `src/` layout** mirroring
  `packages/ai-parrot-tools/pyproject.toml:81-92` (per-backend extras,
  `[tool.setuptools.packages.find]`, `[tool.uv.sources]
  ai-parrot = { workspace = true }`). **Diverge** on the
  `[tool.setuptools.packages.find]` block: use
  `include = ["parrot*"]` + `namespaces = true`, NOT `parrot_tools*`.
- **Dispatch-by-import-string** as used by
  `EmbeddingRegistry._build_model` (registry.py:149-178) — no change
  needed; the satellite-supplied module resolves via merged namespace.
- **Lazy / circular-avoiding local imports** for heavy backends are
  already idiomatic in `bots/abstract.py:82-85,1436` and
  `manager/ephemeral.py:384-385`. Preserved after the move.
- **Per-backend pytest markers** in the satellite tests (e.g.
  `@pytest.mark.requires_pgvector`, `@pytest.mark.requires_milvus`)
  so CI can skip tests whose extras are not installed.
- **`git mv` for backend files** to preserve git blame / history.

### Known Risks / Gotchas

| Risk | Mitigation | Evidence |
|---|---|---|
| **First-of-its-kind namespace extension in this repo.** TASK-548's plan for PEP 420 was reverted to `parrot_<name>.*` in implementation. | Acceptance criteria explicitly require `test_imports_with_satellite_installed` + `test_modules_resolve_to_satellite` + `test_imports_without_satellite_raise_clear_error` (all three; the lattermost is the user-experience guard). | F010, F011 |
| **`images` extra entanglement.** `pgvector==0.4.1` is currently inside the host `images` extra (line 352). | Module 5 explicitly extracts `pgvector` from `images`. Acceptance: `test_host_images_extra_no_pgvector`. | F008 |
| **Meta-extra UX regression.** Existing users running `pip install ai-parrot[all]` must keep working. | Module 5 rewrites `all` / `all-fast` to reach into the satellite. Acceptance: `test_host_all_meta_extra_includes_satellite` + integration test `test_pip_install_ai_parrot_all_meta_extra`. | F008 |
| **Matryoshka kwarg-forwarding (FEAT-150)** and **contextual augmentation (FEAT-127/128)** cross the boundary at `AbstractStore.create_embedding` ↔ `SentenceTransformerModel`. | Module 8 keeps a cross-distribution regression suite. | F013 |
| **`supported_stores` dispatch dict's pre-existing key/class-name mismatch** (`'faiss_store': 'FaissStore'` vs actual `FAISSStore`; `'arango': 'ArangoStore'` vs actual `ArangoDBStore`). | Out of scope for FEAT-201 — do NOT "fix" as part of the packaging refactor. Use direct-class imports in tests; rely on existing dispatch logic for runtime. | F004, `stores/__init__.py:3-10` |
| **Editable-install IDE friction.** Workspaces where both distributions contribute to `parrot.*` can confuse IDEs (PyCharm / VS Code). | Document `uv sync --all-packages` dev workflow in `packages/ai-parrot-embeddings/README.md`; CI gate via Module 7's tests. | F010 |
| **Wheel-build glitches** (e.g. setuptools accidentally including an empty `__init__.py`). | Module 6's `test_satellite_wheel_no_init_at_namespace_levels` inspects the wheel zip directly. | spec design |
| **Circular dependency** `ai-parrot-embeddings` depends on `ai-parrot`; core's `EmbeddingRegistry` resolves backends by string-import from the satellite. | Safe: the registry uses `importlib.import_module` at call time, never at module-load time. Existing lazy-import patterns in `bots/abstract.py` (lines 82-85) confirm this is already the convention. | F006, F012 |
| **CI environment differences.** Backends with heavy native deps (faiss, milvus-lite, pymilvus) may be unavailable on some CI runners. | Per-backend `@pytest.mark.requires_<extra>` markers; CI matrix runs `[all-fast]` profile on the cheap leg and `[all]` on the slow leg. | (operational) |

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `uv` | `>=0.5` | Workspace + members support (already in use) |
| `setuptools` | `>=67.6.1` | Namespace package discovery (already in use; matches host build-system) |
| `wheel` | `>=0.44.0` | Wheel build for verification test (already in use) |
| `build` or `uv build` | latest | Wheel build inside `test_satellite_wheel_no_init_at_namespace_levels` |

No new Python runtime deps introduced by FEAT-201 itself — the per-backend extras
move dependencies from the host to the satellite, they do not add new ones.

---

## 8. Open Questions

### Resolved (carried forward from proposal phase)

- [x] **Scope: just embeddings extras, or the whole retrieval stack?**
  *Resolved in proposal phase*: "move stores, embeddings, rerankers to
  new package ai-parrot-embedding, that is the requirement."
- [x] **Import-stability strategy: top-level rename (sibling precedent)
  or PEP 420 / namespace extension?** *Resolved in proposal phase*:
  "my decision is PEP 420 (namespace package), the other packages were
  moved without take care of PEP 420, but let's stay ai-parrot-embeddings
  using "B" choice."
- [x] **U1: Package name — plural or singular?** *Resolved in
  proposal-phase Q&A*: `ai-parrot-embeddings` (plural), matching the
  `-tools`/`-loaders`/`-pipelines` convention. The singular form was
  treated as a typo.
- [x] **U2: Sub-packages `parrot.stores.{kb,parents,utils}` — stay or
  move?** *Resolved in proposal-phase Q&A*: **All three stay in core.**
  Rationale: higher-level orchestration over `AbstractStore`, not
  backend-specific; keeps the satellite minimal.
- [x] **U3: Satellite `__init__.py` layout?** *Resolved in
  proposal-phase Q&A*: **Pure PEP 420** — satellite omits `__init__.py`
  at `parrot/`, `parrot/embeddings/`, `parrot/stores/`,
  `parrot/rerankers/`. Host retains its existing `__init__.py` files.
  CI-enforced via Module 6's wheel-content test.

### Unresolved (defer to implementation)

- [ ] **Does the `bigquery` host extra need to stay?** Today the host
  pyproject's `bigquery` extra (lines 124-126) declares
  `google-cloud-bigquery>=3.30.0`. The `db` extra (line 120) also
  declares `asyncdb[bigquery,...]` which transitively pulls
  `google-cloud-bigquery`. If `asyncdb[bigquery]` is the canonical way
  to pull the dep for non-vector-store uses, the host's `bigquery`
  extra can be removed entirely (and `ai-parrot-embeddings[bigquery]`
  takes over the vector-store-specific path). If not, the host
  `bigquery` extra stays but no longer overlaps with the satellite
  one. *Owner: Jesus Lara (implementation phase).*
  *Plausible answers*:
    a) Remove host `bigquery` extra entirely (cleaner; relies on
       `db`'s asyncdb extra for non-vector usage).
    b) Keep host `bigquery` for non-vector-store usage; satellite
       gets its own `bigquery` extra for `BigQueryStore`.: keep it

- [ ] **Should existing tests for moved backends move with them or
  remain in `packages/ai-parrot/tests/`?** Following the FEAT-079
  precedent for the formdesigner tests (which moved with the package),
  the satellite likely owns the tests. But cross-distribution
  regression tests (Module 8) live in the satellite. *Owner:
  implementation phase — decide per test file.*

> Both unresolved items are implementation details that do not block
> the design.

---

## Worktree Strategy

- **Isolation unit**: `per-spec` — all tasks run sequentially in one
  worktree.
- **Reason**: every module touches either the new satellite package or
  the host pyproject. Modules 2-4 (the actual file moves) must be
  preceded by Module 1 (scaffold). Module 5 (host pyproject extras
  redistribution) must come after Modules 2-4 because it removes the
  extras whose deps just moved. Modules 6-8 (tests) must come after
  Modules 1-4 because they exercise the satellite. Running these in
  parallel would cause merge conflicts in `pyproject.toml` and in the
  satellite tree.
- **Cross-feature dependencies**: none in flight that touch packaging.
  Recent work on embeddings/stores/rerankers (Matryoshka FEAT-150,
  contextual embedding FEAT-127/128, parent-child retrieval FEAT-128)
  is **already merged to `dev`** per F013 and does not block FEAT-201.
- **Worktree creation** (per `CLAUDE.md` policy):
  ```bash
  git checkout dev && git pull origin dev
  git worktree add -b feat-201-ai-parrot-embeddings \
    .claude/worktrees/feat-201-ai-parrot-embeddings HEAD
  cd .claude/worktrees/feat-201-ai-parrot-embeddings
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-28 | Jesus Lara (via Claude) | Initial draft from `sdd/proposals/ai-parrot-embeddings.proposal.md` |
