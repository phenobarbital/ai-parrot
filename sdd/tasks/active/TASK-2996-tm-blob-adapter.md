# TASK-2996: Implement bounded immutable artifact blob I/O

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2975, TASK-2994
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2973, TASK-2974, TASK-2976 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: B
**Spec acceptance**: AC5, AC6, AC9

---

## Context

Implements §2 Evidence snapshots; durable publication of the approved specification. Delivery B establishes durable continuity; passing in-memory tests alone does not complete this work. Consume the committed contracts from TASK-2975, TASK-2994 before implementation.

## Scope

- Implement a strict adapter over the Phase 0 verified navigator file-manager APIs for Parquet and canonical JSON/text.
- Write immutable scoped blob names, verify readability/checksum, and expose bounded decoded/serialized page loads and deletion/archive primitives.
- Write through supported payloads below and above 64 MiB in durable mode; distinguish content fingerprint from storage checksum and reject unsafe formats.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/blob.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_artifact_blob.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.interfaces.file import FileManagerInterface  # packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18
from parrot.storage.overflow import OverflowStore  # packages/ai-parrot/src/parrot/storage/overflow.py:43
from parrot.tools.repl_worker.transport import encode_dataframe  # packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:55
from pydantic import BaseModel, Field  # packages/ai-parrot/pyproject.toml:54
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18`**

```python
# Verified export; external method signatures must be pinned in the Phase 0 task.
FileManagerInterface
```

Navigator file-manager interface plus local/temp managers are re-exported eagerly; S3/GCS are lazy exports.

**`packages/ai-parrot/src/parrot/storage/overflow.py:43`**

```python
async def maybe_offload(self, data: Dict[str, Any], key_prefix: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
```

Existing JSON definition overflow calls file_manager.create_from_bytes at 67 and falls back to inline data on write failure at 80.

**`packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:55`**

```python
def encode_dataframe(df: pd.DataFrame, name: str) -> EncodedDataFrame:
```

Arrow conversion failure branches to pickle.dumps at 81; EncodedDataFrame carries format/shm_name/size/payload.

**`packages/ai-parrot/pyproject.toml:54`**

```python
# Dependency declarations: Python >=3.11; pydantic ==2.12.5;
# pandas >=2.0.0; pyarrow >=25.0; orjson >=3.9;
# existing graphindex-postgres extra: asyncpg >=0.29.
```

Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.

### Does NOT Exist

- No versioned Parquet task store is provided by this compatibility shim; do not invent external stream/stat methods.
- No strict task-evidence publish guarantee or bounded Parquet reader exists here; inline fallback is unsuitable for durable evidence.
- No guarantee of pickle-free transport exists without an explicit strict branch.
- No new qworker/ULID/task-memory dependency is authorized; do not assume stdlib uuid7 on Python 3.11.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

Local integration requires a persistent shared mount for production durability; use temporary storage only in tests.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/src/parrot/interfaces/file/__init__.py:18` — Navigator file-manager interface plus local/temp managers are re-exported eagerly; S3/GCS are lazy exports.
- `packages/ai-parrot/src/parrot/storage/overflow.py:43` — Existing JSON definition overflow calls file_manager.create_from_bytes at 67 and falls back to inline data on write failure at 80.
- `packages/ai-parrot/src/parrot/tools/repl_worker/transport.py:55` — Arrow conversion failure branches to pickle.dumps at 81; EncodedDataFrame carries format/shm_name/size/payload.
- `packages/ai-parrot/pyproject.toml:54` — Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.

## Acceptance Criteria

- [ ] Supported frame/text/JSON fingerprints survive blob round-trip, including schema/index metadata.
- [ ] Small page reads never fully materialize oversized tables; encoded/decoded byte ceilings hold.
- [ ] Failed upload/stat/checksum returns no publishable reference; no pickle or implicit oversized inline fallback.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC5, AC6, AC9 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_artifact_blob.py -q`; retain output in `artifacts/logs/task-2996-tm-blob-adapter.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_roundtrip` | Supported frame/text/JSON fingerprints survive blob round-trip, including schema/index metadata. |
| `test_bounded_page` | Small page reads never fully materialize oversized tables; encoded/decoded byte ceilings hold. |
| `test_failed_publish` | Failed upload/stat/checksum returns no publishable reference; no pickle or implicit oversized inline fallback. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2996-tm-blob-adapter.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

Not completed. The implementing agent records completed-by, date, verification evidence, notes, and any approved deviations here when acceptance passes.
