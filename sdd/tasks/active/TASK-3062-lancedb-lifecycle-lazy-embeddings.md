# TASK-3062: Implement async lifecycle and lazy embedding ownership

**Feature**: FEAT-542 - Local LanceDB Vector, Full-Text and Hybrid Search
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

**Completed by**: not started
**Date**: not completed
**Notes**: Pending execution; no implementation or acceptance tests run during task decomposition.
**Deviations from spec**: The checked answers supersede stale prose; TASK-3057 reconciles that discrepancy before implementation.
