# TASK-3062: Implement async lifecycle and lazy embedding ownership

**Feature**: FEAT-542 — Local LanceDB Vector, Full-Text and Hybrid Search
**Spec**: `sdd/specs/lancedb-vector-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h) — target 4 hours
**Depends-on**: TASK-3058, TASK-3059, TASK-3061
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Sequential/gated task. The subclass may remain abstract until later tasks implement inherited operations; lifecycle tests may use a concrete test-only harness. Register only after all operations are complete. Shared backend edits are sequential.
**Acceptance coverage**: AC3, AC4, AC6, AC8

---

## Context

M2 lifecycle foundation. Connection and lexical access must not eagerly create a model, and all mutations will use the process-safe coordinator.

The spec is marked approved. Its checked section 8 answers require fully offline agent operation after provisioning, concurrent independent writers, graph federation only, and whole-origin failure; they override older draft assumptions. TASK-3057 must reconcile the spec and prove the SDK/offline/concurrency contracts before dependent implementation begins. Do not reinstate single-writer-only or storage-only-offline behavior.

---

## Scope

- Create the AbstractStore subclass with lazy SDK import and subclass-local provider setup; avoid the base constructor's eager embedding path and preserve borrowed provider ownership.
- Implement idempotent connection/disconnect, synchronous accessors without hidden I/O, nested contexts, in-flight tracking and safe shutdown.
- Prepare persistent versioned schema/native FTS under process-safe coordination; compatible creation is idempotent and incompatible reopen never overwrites data.
- Normalize collection/table, default column/schema aliases, FLAT/COSINE and provider/context settings; ensure engine/connected state agrees with real lifecycle. Complete prepare_embedding_table's documented compatibility behavior. Explicitly consume verified factory routing fields such as name/vector_database instead of rejecting them as unknown query options; re-read the full factory payload before implementing normalization.
- Construct a configured provider only on demand off the event loop; cache first-use initialization safely and never call free on injected or registry-shared models. Propagate approved offline provider configuration rather than silently defaulting to a remote/model-download path.

**NOT in scope**: CRUD, vector/FTS/hybrid search implementation, public dispatch and permanent no-op implementations of unfinished methods.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py` | CREATE | Backend lifecycle, collection setup and compatibility normalization |
| `packages/ai-parrot-embeddings/tests/test_lancedb_lifecycle.py` | CREATE | Lifecycle/schema/provider ownership tests |

Ownership is exclusive to this task for the listed responsibility. You are not alone in the codebase: preserve others' changes, do not revert unrelated edits, and accommodate completed dependency work. New files listed here are proposed outputs, not already-verified imports. Shared backend files are deliberately sequenced by dependencies.

---

## Codebase Contract (Anti-Hallucination)

Verified by source inspection on `dev` on 2026-09-10. This is not a claim of runtime SDK/import testing. Re-read relevant definitions before implementation; if paths/signatures changed, update the contract first. Symbols delivered by dependencies must be verified in their committed files before import.

### Verified Imports

```python
from parrot.stores import AbstractStore  # packages/ai-parrot-embeddings/tests/test_namespace_imports.py:151
from pydantic import BaseModel, Field  # packages/ai-parrot/src/parrot/stores/models.py:13
from parrot.models.stores import SearchResult  # packages/ai-parrot-tools/src/parrot_tools/multistoresearch/origins/vector.py:11
```

### Existing Signatures to Use

| Verified source | Existing contract |
|---|---|
| `packages/ai-parrot/src/parrot/stores/abstract.py:117` | AbstractStore.__init__(self, embedding_model: Union[dict, str] = None, embedding: Union[dict, Callable] = None, **kwargs); configured provider eagerly created at :155. |
| `packages/ai-parrot/src/parrot/interfaces/vector.py:42` | _get_database_store(self, store: dict) -> AbstractStore; forwards the store dictionary, including name and embedding fields, to the dynamically imported constructor. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:202` | async connection(self) -> tuple; get_connection(self) -> Any at :205; engine(self) at :208; async disconnect(self) -> None at :212. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:216` | Nested __aenter__/__aexit__; _free_resources at :222 calls provider.free(). Subclass must preserve borrowed-provider ownership. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:238` | get_vector(self, metric_type: str = None, **kwargs); get_vectorstore(self) at :241 delegates. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:276` | async from_documents(self, documents: List[Any], collection: Union[str, None] = None, **kwargs) -> Callable. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:295` | async create_collection(self, collection: str) -> None; async add_documents(self, documents: List[Any], collection: Union[str, None] = None, **kwargs) -> None at :308. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:455` | async prepare_embedding_table(self, tablename: str, conn: Any = None, embedding_column: str = 'embedding', document_column: str = 'document', metadata_column: str = 'cmetadata', dimension: int = None, id_column: str = 'id', use_jsonb: bool = True, drop_columns: bool = False, create_all_indexes: bool = True, **kwargs). |
| `packages/ai-parrot/src/parrot/stores/abstract.py:494` | async delete_documents(self, documents: Optional[Any] = None, pk: str = 'source_type', values: Optional[Union[str, List[str]]] = None, table: Optional[str] = None, schema: Optional[str] = None, collection: Optional[str] = None, **kwargs) -> int. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:520` | async delete_documents_by_filter(self, search_filter: Dict[str, Union[str, List[str]]], table: Optional[str] = None, schema: Optional[str] = None, collection: Optional[str] = None, **kwargs) -> int. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:326` | create_embedding(self, embedding_model: dict, **kwargs) uses registry.get_or_create_sync; arbitrary dict fields are not automatically forwarded (Matryoshka is explicitly forwarded). |
| `packages/ai-parrot/src/parrot/stores/abstract.py:383` | async generate_embedding(self, documents: List[Any]) -> List[Any] initializes a default provider if absent, then awaits embed_documents. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:391` | _apply_contextual_augmentation(self, documents: list, _log: bool = True) -> list[str] mutates document.metadata['contextual_header']; use copies. |
| `packages/ai-parrot/src/parrot/embeddings/base.py:169` | async embed_documents(self, texts: List[str], batch_size: Optional[int] = None) -> List[List[float]]. |
| `packages/ai-parrot/src/parrot/embeddings/base.py:188` | async embed_query(self, text: str, as_nparray: bool = False) -> Union[List[float], List[np.ndarray]]; default is a single flat vector. |
| `packages/ai-parrot-embeddings/src/parrot/embeddings/huggingface.py:134` | SentenceTransformerModel.__init__(self, model_name: str, matryoshka: Optional[dict] = None, backend: Optional[str] = None, file_name: Optional[str] = None, **kwargs). |
| `packages/ai-parrot/src/parrot/stores/models.py:19` | Document(page_content: str, metadata: Dict[str, Any]); metadata defaults to an empty mapping. |
| `packages/ai-parrot/src/parrot/models/stores.py:46` | SearchResult requires id: str, content: str, score: float; distance at :74 returns score unchanged. |
| `packages/ai-parrot/src/parrot/models/stores.py:79` | OriginHit has optional id/score, content/metadata, origin, origin_kind and native_rank >= 1. |
| `packages/ai-parrot/src/parrot/models/stores.py:162` | StoreConfig has embedding_model, dimension=768, metric_type='COSINE', index_type='IVF_FLAT', table/schema/dsn and extra. |

### Does NOT Exist

- LanceDBStore and a LanceDB process-shared coordinator do not yet exist.
- AbstractStore's connection/context state is not a cross-process transaction mechanism.
- Calling base generate_embedding is not model-free lexical retrieval.
- Do not assume arbitrary offline/local_files_only fields in embedding_model reach the provider; verify forwarding before relying on them.
- LanceDBConfig, LanceDBHybridHit and lancedb_models.py are new task deliverables, not current core types.
- A shared HybridSearchResult or globally comparable origin score does not exist.
- New helpers listed in dependency tasks are not pre-existing repository APIs. Use the gate/completion contracts, then verify their actual implementations.
- No guarantee of fully offline inference or concurrent-process correctness follows merely from opening a local LanceDB directory.

---

## Implementation Notes

### Pattern to Follow

The subclass may remain abstract until later tasks implement inherited operations; lifecycle tests may use a concrete test-only harness. Register only after all operations are complete. Shared backend edits are sequential.

Use the existing contracts above without changing unrelated shared behavior. Keep async public operations non-blocking, strict type hints, Pydantic structured records and black/isort formatting. Keep SDK access inside the embeddings backend, never in the origin adapter.

### Key Constraints

- Complete only this task's deliverable; do not implement later tasks opportunistically.
- Never remove or silently downgrade approved offline or concurrent-writer requirements.
- No schema overwrite, broad deletion, automatic version pruning, remote fallback or new storage server.
- Preserve caller documents and shared embedding ownership. Do not log document text, vectors, credentials or filter values.
- Respect optional dependency boundaries; follow approval policy before introducing unapproved packages.
- Capture test commands, dependency versions and outcomes under `artifacts/logs/TASK-3062-lancedb.log`; real-model/benchmark evidence must distinguish provisioning from execution.

### References in Codebase

The task-specific locations above and the spec's sections 2, 4, 5, 6 and 8 are authoritative. Read any additional implementation API before relying on it; do not guess builder methods from a class name.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Blocks were derived from
> the spec's §2 New Public Interfaces and re-verified against the Codebase Contract above
> when this task was written. This is NOT the full implementation: business-logic branches,
> edge cases and test bodies are `FILL IN` stubs by design. Never change a signature, class
> name, or file path the blueprint fixes.

### Steps (in order)
1. Initialize base state WITHOUT embedding arguments, then store normalized settings on the subclass — *why*: `AbstractStore.__init__` eagerly creates the configured provider at `abstract.py:155`, and spec §2 item 1 requires FTS-only reopen to work with no model constructed. Do not refactor the base class.
2. Import the SDK inside methods, never at module top level — *why*: `parrot.stores.lancedb` must be importable without the extra for TASK-3058's guard and TASK-3067's dispatch test to pass.
3. Make `connection()` idempotent and non-creating — *why*: spec §2 item 2 says connecting alone never creates or replaces a collection; a create-on-connect is silent data creation.
4. Override `_free_resources` to release borrowed providers without calling `free()` — *why*: `abstract.py:222` calls `provider.free()`, which would destroy a registry-shared model another store is using (AC4).
5. Leave every query method to TASK-3064/3065 as an explicit stub — *why*: this task owns lifecycle only; a half-written search here collides with the tasks that own it.

### `packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py` (CREATE)
```python
"""LanceDB backend: lifecycle, collection setup and compatibility normalization.

Query methods are declared here but implemented by TASK-3064 (vector) and
TASK-3065 (FTS/hybrid). The SDK is imported lazily inside methods so this module
stays importable without ``ai-parrot-embeddings[lancedb]``.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, List, Union

from parrot.stores import AbstractStore  # verified: packages/ai-parrot-embeddings/tests/test_namespace_imports.py:151
from parrot.stores.lancedb_concurrency import MutationCoordinator  # new in TASK-3061
from parrot.stores.lancedb_models import CollectionManifest, LanceDBConfig  # new in TASK-3059


class LanceDBStore(AbstractStore):
    """Embedded vector, full-text and hybrid store over a local directory."""

    def __init__(self, embedding_model=None, embedding=None, **kwargs: Any) -> None:
        self.logger = logging.getLogger(__name__)
        # FILL IN: call super().__init__() WITHOUT embedding_model/embedding so the base
        # does not eagerly construct a provider (abstract.py:155), then keep the normalized
        # provider settings on self for lazy construction — bounded by spec §2 item 1, AC6
        self._config: LanceDBConfig = ...  # FILL IN: build from kwargs incl. table/uri aliases
        self._manifest: CollectionManifest | None = None
        self._coordinator: MutationCoordinator | None = None
        raise NotImplementedError

    async def _ensure_provider(self):
        """Construct the embedding provider on first vector use, never for FTS."""
        # FILL IN: single-flight construction under a lock; must remain uncalled on the
        # FTS path — bounded by AC6 and the provider call counters in lancedb_fixtures
        raise NotImplementedError

    async def connection(self) -> tuple:
        """Open the directory and return ``(connection, default_table_or_none)``.

        Idempotent. Never creates or replaces a collection.
        """
        # FILL IN: lazy `import lancedb`; connect_async against the canonical uri with the
        # configured read consistency; cache handles — bounded by spec §2 item 2, AC3
        raise NotImplementedError

    def get_vector(self, metric_type: str = None, **kwargs: Any):
        """Return the already-open default table, or raise.

        Raises:
            RuntimeError: the store is not connected. This accessor performs no I/O.
        """
        # FILL IN — bounded by spec §2 item 2 (synchronous accessors do no async I/O)
        raise NotImplementedError

    async def create_collection(self, collection: str) -> None:
        """Create the Arrow schema and the native FTS index when missing.

        Idempotent on a compatible existing collection. A failed FTS setup leaves an
        explicit initialization error, never a successful searchable collection.
        """
        # FILL IN: run under the coordinator's exclusive section (TASK-3061); use the async
        # index API, NOT create_fts_index; never overwrite an existing table
        # — bounded by spec §2 item 3, §7 "Async/native FTS API drift", AC3
        raise NotImplementedError

    async def prepare_embedding_table(self, tablename: str, conn: Any = None, **kwargs: Any) -> None:
        """Legacy-compatible alias for :meth:`create_collection`."""
        # FILL IN: accept conn=None or this store's connection, default column labels and
        # use_jsonb=True as a compatibility-only flag; reject drop_columns=True, foreign
        # connections and schema-changing options; FTS preparation happens even when
        # create_all_indexes is False — bounded by spec §2 last paragraph, AC2
        raise NotImplementedError

```
**Why this block**: construction, provider laziness and collection setup are the three places AC6 and AC3 can be lost, so they are read together. Do not move the lazy-provider logic into the base class.

### `packages/ai-parrot-embeddings/src/parrot/stores/lancedb.py` (CREATE — part 2, same file)
```python
    async def disconnect(self) -> None:
        """Idempotent shutdown; waits for this store's in-flight operations."""
        # FILL IN: nested contexts close only at the outermost exit — bounded by AC8
        raise NotImplementedError

    def _free_resources(self) -> None:
        """Release borrowed providers WITHOUT calling their ``free()``."""
        # FILL IN: drop references only — the base implementation at abstract.py:222 calls
        # provider.free(), which would destroy a registry-shared model — bounded by AC4
        raise NotImplementedError

    async def similarity_search(self, query: str, collection=None, limit: int = 2, **kwargs: Any) -> list:
        """Implemented by TASK-3064."""
        raise NotImplementedError("TASK-3064 owns vector search")

    async def fulltext_search(self, query: str, collection=None, limit: int = 10, **kwargs: Any) -> list:
        """Implemented by TASK-3065."""
        raise NotImplementedError("TASK-3065 owns FTS")

    async def hybrid_search(self, query: str, collection=None, limit: int = 10, **kwargs: Any) -> list:
        """Implemented by TASK-3065."""
        raise NotImplementedError("TASK-3065 owns hybrid search")

    async def mmr_search(self, **kwargs: Any) -> list:
        """Always raises: v1 supports exact similarity search only."""
        raise NotImplementedError(
            "LanceDBStore does not support MMR; v1 provides exact cosine search only."
        )
```
**Why this shape**: the three query stubs exist so TASK-3063/3064/3065 have a verified anchor to attach to rather than inventing one, and so an executor who runs the class early gets an honest failure instead of a missing attribute. `mmr_search` raises with a message rather than being absent, because the existing vector tool has an opt-in MMR path that must fail clearly (spec §2). Do not remove `_free_resources` — it is the single line standing between this backend and freeing another store's shared model.

### `packages/ai-parrot-embeddings/tests/test_lancedb_lifecycle.py` (CREATE)
```python
"""Lifecycle, schema and provider-ownership tests (FEAT-542, AC3/AC4/AC6/AC8)."""
from __future__ import annotations

import pytest

from parrot.stores.lancedb import LanceDBStore

pytestmark = pytest.mark.asyncio


class TestLazyProvider:
    async def test_construction_does_not_build_a_provider(self, tmp_path):
        # FILL IN: provider factory that raises if touched — bounded by AC6
        raise NotImplementedError

    async def test_concurrent_first_use_constructs_exactly_once(self, tmp_path):
        # FILL IN: gather N vector calls, assert one construction — bounded by AC6
        raise NotImplementedError


class TestConnection:
    async def test_connect_is_idempotent_and_creates_nothing(self, tmp_path):
        # FILL IN — bounded by spec §2 item 2
        raise NotImplementedError

    async def test_get_vector_raises_when_not_connected(self, tmp_path):
        # FILL IN: RuntimeError, no I/O — bounded by spec §2 item 2
        raise NotImplementedError


class TestCollection:
    async def test_failed_fts_setup_leaves_an_error_not_a_searchable_collection(self, tmp_path):
        # FILL IN — bounded by spec §2 item 3
        raise NotImplementedError

    async def test_retry_completes_index_prep_without_replacing_rows(self, tmp_path):
        # FILL IN — bounded by AC3
        raise NotImplementedError


class TestOwnership:
    async def test_borrowed_provider_is_never_freed(self, tmp_path):
        # FILL IN: injected provider with a free() that fails the test if called
        # — bounded by AC4
        raise NotImplementedError

    async def test_nested_context_closes_only_at_outermost_exit(self, tmp_path):
        # FILL IN — bounded by AC8
        raise NotImplementedError

    async def test_event_loop_heartbeat_advances_during_blocking_work(self, tmp_path):
        # FILL IN: 200ms blocking fixture, 10ms heartbeat, >= 5 ticks
        # — bounded by spec §4 "Test Data / Fixtures"
        raise NotImplementedError
```
**Why this shape**: `test_construction_does_not_build_a_provider` uses a factory that *raises* rather than a counter, because a counter test passes if the provider is built lazily-but-eagerly on the FTS path; a raising factory fails loudly at the exact moment AC6 is violated.

### FILL IN checklist
- [ ] `lancedb.py::__init__` — base init without embedding args, config normalization; bounded by spec §2 item 1, AC6
- [ ] `lancedb.py::_ensure_provider` — single-flight lazy construction; bounded by AC6
- [ ] `lancedb.py::connection` / `get_vector` — idempotent, non-creating, no I/O in the accessor; bounded by spec §2 item 2
- [ ] `lancedb.py::create_collection` / `prepare_embedding_table` — schema + native FTS, legacy arg mapping; bounded by AC2/AC3
- [ ] `lancedb.py::disconnect` / `_free_resources` — nested contexts, borrowed providers; bounded by AC4/AC8
- [ ] `test_lancedb_lifecycle.py` — all nine bodies; bounded by AC3/AC4/AC6/AC8
- [ ] Leave `similarity_search` / `fulltext_search` / `hybrid_search` as stubs for TASK-3064/3065

---

## Acceptance Criteria

- [ ] Connection/collection setup persists data and rejects mismatches non-destructively.
- [ ] All lifecycle/provider ownership and heartbeat tests pass.
- [ ] Process-safe coordinator guards creation/index setup and shutdown respects in-flight writes.
- [ ] No fabricated search/delete stubs are added to make an incomplete store appear production-ready.
- [ ] Tests in this task's Test Specification pass; failures are not hidden by mocks, skips or relaxed assertions where real SDK/model execution is required.
- [ ] Scope-owned code passes formatting/type checks appropriate to the repository, and the completion note records actual commands and evidence.

---

## Test Specification

| Test | Required behavior |
|---|---|
| `test_connect_nested_context_and_reopen` | Idempotent lifecycle, manifest validation and parent context ownership. |
| `test_lexical_setup_never_constructs_provider` | Connection and FTS setup succeed even if model construction would raise. |
| `test_borrowed_provider_not_freed` | Store cleanup cannot invalidate another consumer's provider. |
| `test_provider_init_and_arrow_conversion_offloaded` | 10 ms heartbeat advances at least five times during a 200 ms blocking fixture. |

Intended command after dependencies are implemented:

```bash
uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_lifecycle.py -v
```

These are test contracts, not executed test results or placeholder production implementations. Use pytest-asyncio for async cases, temporary directories for datasets, bounded subprocess joins, and explicit process barriers for race tests. Reuse the deterministic 8-D fixture unless real local model evidence is explicitly required. Required feature tests may not all skip just because the SDK or assets were omitted.

---

## Agent Instructions

1. Read the spec and the approved-answer precedence in this task.
2. Work only inside the FEAT-542 feature worktree. Verify dependency tasks are `done` in `sdd/tasks/index/lancedb-vector-store.json` and their task files are under `sdd/tasks/completed/`.
3. Re-verify every needed import/signature and dependency-produced helper before writing code.
4. Update only this task entry in `sdd/tasks/index/lancedb-vector-store.json` to `in-progress`, with assignment/start timestamps. Never use the historical monolithic index.
5. Outline the implementation plan and uncertainties, then implement within the listed file ownership. Preserve unrelated work.
6. Run all task acceptance checks and save logs; unresolved gate failures prevent completion.
7. Move this task to `sdd/tasks/completed/TASK-3062-lancedb-lifecycle-lazy-embeddings.md`, update its per-spec entry to `done` with completion time and file path, and fill the completion note.
8. Commit only scoped implementation plus this task's SDD state. Follow the execution/review workflow before pushing.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-10
**Notes**: Implemented `LanceDBStore(AbstractStore)` per blueprint. Constructor: pops factory-routing kwargs (`name`/`vector_database`/`vector_store`), validates `schema` (None/"public" only) and `dsn` (must be null), forwards contextual-embedding base kwargs, rejects any remaining key not in `LanceDBConfig.model_fields | {"table"}`, then calls `super().__init__()` with NO `embedding_model`/`embedding` (avoiding `abstract.py:155`'s eager provider construction) before building `self._config = LanceDBConfig(**remaining)`. `_ensure_provider()` single-flight-constructs under `asyncio.Lock` + `asyncio.to_thread(self.create_embedding, ...)`, mirrors into `self._embed_` for base-class coherence, and is never called by the FTS path. `connection()`/`get_vector()` are idempotent, create nothing, and the accessor does zero I/O. `create_collection()` runs its whole body (reopen-or-create + FTS-index-idempotent-check) inside `self._coordinator.run_mutation(...)` (TASK-3061), builds the manifest via `lancedb_models.build_arrow_schema`/`CollectionManifest`, and calls `manifest.check_compatible()` on reopen (non-destructive). `prepare_embedding_table()` rejects `drop_columns=True`, non-default column labels, `additional_columns`, and a foreign `conn`, then delegates to `create_collection`. `_free_resources()` drops `self._embedding_provider`/`self._embed_` without calling `.free()`.

`test_lancedb_lifecycle.py`: 17 tests, all pass (`uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_lifecycle.py -v`, log at `artifacts/logs/TASK-3062-lancedb.log`). Full lancedb-scoped suite (`-k lancedb` across all 6 FEAT-542 test modules so far): 80/80 passing. Verified `parrot.stores.lancedb` imports and instantiates cleanly with `lancedb` unimportable (blocked-import guard). `ruff check` clean.
**Deviations from spec**: None. Query methods (`similarity_search`, `from_documents`, `add_documents`, `delete_documents`, `delete_documents_by_filter`, `fulltext_search`, `hybrid_search`) are explicit `NotImplementedError` stubs naming their owning task, per this task's NOT-in-scope boundary; `mmr_search` always raises per spec §2. The class is fully concrete/instantiable already (every abstract method from `AbstractStore` has a real override, even the stubs), which is a stronger position than the task's "may remain abstract" allowance — no test-only harness was needed for lifecycle testing.
