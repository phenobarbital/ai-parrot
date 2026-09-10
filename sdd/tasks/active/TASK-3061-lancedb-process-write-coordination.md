# TASK-3061: Implement process-safe mutation coordination

**Feature**: FEAT-542 - Local LanceDB Vector, Full-Text and Hybrid Search
**Spec**: `sdd/specs/lancedb-vector-store.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h) — target 4 hours
**Depends-on**: TASK-3057, TASK-3059
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Can run alongside filters and the origin adapter after models. File ownership is disjoint from other eligible parallel tasks; dependencies still gate start.
**Acceptance coverage**: AC8, AC4

---

## Context

Refines M2 to implement the user's concurrent-writer requirement. Multiple independent processes must safely use the same local collection.

The spec is marked approved. Its checked section 8 answers require fully offline agent operation after provisioning, concurrent independent writers, graph federation only, and whole-origin failure; they override older draft assumptions. TASK-3057 must reconcile the spec and prove the SDK/offline/concurrency contracts before dependent implementation begins. Do not reinstate single-writer-only or storage-only-offline behavior.

---

## Scope

- Implement the coordinator interface and configuration frozen in TASK-3057, keyed by canonical dataset/collection identity. Do not substitute a one-process-only asyncio lock.
- Cover collection creation and FTS index setup as well as upsert and count/delete transactions. Keep waits off the event loop and bound contention per the reconciled spec.
- Ensure independently opened handles observe the latest committed snapshot before mutations; use the exact refresh/retry contract from the gate.
- Define lock/resource ownership through cancellation, write completion and shutdown. If using OS lock files, do not unlink active lock paths or steal ownership using an unsafe age/PID heuristic; ensure process death releases ownership according to the chosen primitive.

**NOT in scope**: CRUD algorithms, model loading, distributed/network filesystem locks, new database server or daemon.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-embeddings/src/parrot/stores/lancedb_concurrency.py` | CREATE | Gate-defined async process-shared mutation coordinator |
| `packages/ai-parrot-embeddings/tests/test_lancedb_concurrency.py` | CREATE | Real process coordination, failure and cancellation tests |

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
| `packages/ai-parrot/src/parrot/stores/abstract.py:202` | async connection(self) -> tuple; get_connection(self) -> Any at :205; engine(self) at :208; async disconnect(self) -> None at :212. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:216` | Nested __aenter__/__aexit__; _free_resources at :222 calls provider.free(). Subclass must preserve borrowed-provider ownership. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:238` | get_vector(self, metric_type: str = None, **kwargs); get_vectorstore(self) at :241 delegates. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:276` | async from_documents(self, documents: List[Any], collection: Union[str, None] = None, **kwargs) -> Callable. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:295` | async create_collection(self, collection: str) -> None; async add_documents(self, documents: List[Any], collection: Union[str, None] = None, **kwargs) -> None at :308. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:455` | async prepare_embedding_table(self, tablename: str, conn: Any = None, embedding_column: str = 'embedding', document_column: str = 'document', metadata_column: str = 'cmetadata', dimension: int = None, id_column: str = 'id', use_jsonb: bool = True, drop_columns: bool = False, create_all_indexes: bool = True, **kwargs). |
| `packages/ai-parrot/src/parrot/stores/abstract.py:494` | async delete_documents(self, documents: Optional[Any] = None, pk: str = 'source_type', values: Optional[Union[str, List[str]]] = None, table: Optional[str] = None, schema: Optional[str] = None, collection: Optional[str] = None, **kwargs) -> int. |
| `packages/ai-parrot/src/parrot/stores/abstract.py:520` | async delete_documents_by_filter(self, search_filter: Dict[str, Union[str, List[str]]], table: Optional[str] = None, schema: Optional[str] = None, collection: Optional[str] = None, **kwargs) -> int. |
| `packages/ai-parrot/src/parrot/stores/models.py:19` | Document(page_content: str, metadata: Dict[str, Any]); metadata defaults to an empty mapping. |
| `packages/ai-parrot/src/parrot/models/stores.py:46` | SearchResult requires id: str, content: str, score: float; distance at :74 returns score unchanged. |
| `packages/ai-parrot/src/parrot/models/stores.py:79` | OriginHit has optional id/score, content/metadata, origin, origin_kind and native_rank >= 1. |
| `packages/ai-parrot/src/parrot/models/stores.py:162` | StoreConfig has embedding_model, dimension=768, metric_type='COSINE', index_type='IVF_FLAT', table/schema/dsn and extra. |

### Does NOT Exist

- LanceDBStore and a LanceDB process-shared coordinator do not yet exist.
- AbstractStore's connection/context state is not a cross-process transaction mechanism.
- LanceDBConfig, LanceDBHybridHit and lancedb_models.py are new task deliverables, not current core types.
- A shared HybridSearchResult or globally comparable origin score does not exist.
- New helpers listed in dependency tasks are not pre-existing repository APIs. Use the gate/completion contracts, then verify their actual implementations.
- No guarantee of fully offline inference or concurrent-process correctness follows merely from opening a local LanceDB directory.

---

## Implementation Notes

### Pattern to Follow

Can run alongside filters and the origin adapter after models. Store integration happens in dependent tasks; this task tests the primitive using deterministic critical-section workers.

Use the existing contracts above without changing unrelated shared behavior. Keep async public operations non-blocking, strict type hints, Pydantic structured records and black/isort formatting. Keep SDK access inside the embeddings backend, never in the origin adapter.

### Key Constraints

- Complete only this task's deliverable; do not implement later tasks opportunistically.
- Never remove or silently downgrade approved offline or concurrent-writer requirements.
- No schema overwrite, broad deletion, automatic version pruning, remote fallback or new storage server.
- Preserve caller documents and shared embedding ownership. Do not log document text, vectors, credentials or filter values.
- Respect optional dependency boundaries; follow approval policy before introducing unapproved packages.
- Capture test commands, dependency versions and outcomes under `artifacts/logs/TASK-3061-lancedb.log`; real-model/benchmark evidence must distinguish provisioning from execution.

### References in Codebase

The task-specific locations above and the spec's sections 2, 4, 5, 6 and 8 are authoritative. Read any additional implementation API before relying on it; do not guess builder methods from a class name.

---

## Acceptance Criteria

- [ ] Actual multiprocessing tests pass; same-event-loop simulation is not accepted as cross-process evidence.
- [ ] Wait/timeout/cancellation semantics match gate decisions and heartbeat remains responsive.
- [ ] No successful mutation can bypass process-safe coordination or operate on a stale pre-lock snapshot.
- [ ] Coordinator module exposes documented, typed interfaces consumed by lifecycle/CRUD tasks.
- [ ] Tests in this task's Test Specification pass; failures are not hidden by mocks, skips or relaxed assertions where real SDK/model execution is required.
- [ ] Scope-owned code passes formatting/type checks appropriate to the repository, and the completion note records actual commands and evidence.

---

## Test Specification

| Test | Required behavior |
|---|---|
| `test_two_processes_share_mutation_exclusion` | Separate processes begin concurrently but critical sections follow the proven transaction contract. |
| `test_crashed_owner_does_not_deadlock_successor` | Terminated worker cannot permanently prevent subsequent progress. |
| `test_cancelled_waiter_does_not_release_owner` | Cancellation before acquisition and after native operation start preserves ownership. |
| `test_canonical_paths_share_coordination_key` | Equivalent local paths coordinate; distinct collections retain isolation. |

Intended command after dependencies are implemented:

```bash
uv run pytest packages/ai-parrot-embeddings/tests/test_lancedb_concurrency.py -v
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
7. Move this task to `sdd/tasks/completed/TASK-3061-lancedb-process-write-coordination.md`, update its per-spec entry to `done` with completion time and file path, and fill the completion note.
8. Commit only scoped implementation plus this task's SDD state. Follow the execution/review workflow before pushing.

---

## Completion Note

**Completed by**: not started
**Date**: not completed
**Notes**: Pending execution; no implementation or acceptance tests run during task decomposition.
**Deviations from spec**: The checked answers supersede stale prose; TASK-3057 reconciles that discrepancy before implementation.
