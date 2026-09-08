# TASK-2997: Implement atomic durable aliases, versions and evidence pins

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2976, TASK-2995, TASK-2996
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2977, TASK-2979, TASK-2980 after prerequisites. Shared-file predecessors: TASK-2995; do not edit their files concurrently.
**Delivery**: B
**Spec acceptance**: AC2, AC5, AC6, AC9, AC11, AC12

---

## Context

Implements §2 Durable artifact publish order of the approved specification. Delivery B establishes durable continuity; passing in-memory tests alone does not complete this work. Consume the committed contracts from TASK-2976, TASK-2995, TASK-2996 before implementation.

## Scope

- Implement PostgresArtifactStore as the catalog backend using blob adapter and the shared task transaction coordinator.
- Serialize scoped alias version allocation, preserve tombstones and cross-task pins, and atomically append artifact_registered with its index/alias rows.
- Publish in-process cache only after commit; implement consistent descriptor pages/version loads and expose orphan-safe publication ownership.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/store/postgres.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_postgres_artifacts.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.tools.working_memory.internals import WorkingMemoryCatalog, CatalogEntry, GenericEntry  # packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542
from pydantic import BaseModel, Field  # packages/ai-parrot/pyproject.toml:54
from parrot.bots.flows.plan.models import ArtifactRef, ExecutionManifest  # packages/ai-parrot/src/parrot/bots/flows/plan/models.py:413
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542`**

```python
def get(self, key: str) -> CatalogEntry | GenericEntry:
def drop(self, key: str) -> bool:
```

GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.

**`packages/ai-parrot/pyproject.toml:54`**

```python
# Dependency declarations: Python >=3.11; pydantic ==2.12.5;
# pandas >=2.0.0; pyarrow >=25.0; orjson >=3.9;
# existing graphindex-postgres extra: asyncpg >=0.29.
```

Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.

**`packages/ai-parrot/src/parrot/bots/flows/plan/models.py:413`**

```python
class ArtifactRef(BaseModel):
    node_id: str
    keys: List[str]
    status: Literal["ok", "skipped", "partial", "error"]
```

ArtifactRef carries alias keys, small facets/error status/bytes_stored; ExecutionManifest at 444 aggregates refs and nodes_failed.

### Does NOT Exist

- No awaited catalog backend, versioned evidence metadata, locks or to_descriptor method exists at this commit.
- No new qworker/ULID/task-memory dependency is authorized; do not assume stdlib uuid7 on Python 3.11.
- No immutable artifact_id@version references or domain-step mapping is currently encoded in the manifest.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

Sequential owner of store/postgres.py after durable task-store work.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542` — GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.
- `packages/ai-parrot/pyproject.toml:54` — Navigator-api >=3.2.2 is declared at 104; pyarrow at 157 and asyncpg optional dependency at 258. Reuse existing libraries and lazy startup checks.
- `packages/ai-parrot/src/parrot/bots/flows/plan/models.py:413` — ArtifactRef carries alias keys, small facets/error status/bytes_stored; ExecutionManifest at 444 aggregates refs and nodes_failed.

## Acceptance Criteria

- [ ] Crash after blob write leaves an orphan; rollback never leaves an index referencing unavailable bytes or a journal-only registration.
- [ ] Concurrent writers produce distinct versions with one consistent current alias and old evidence intact.
- [ ] Cross-task evidence survives producer terminal state and restart; every lookup checks trusted scope.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC2, AC5, AC6, AC9, AC11, AC12 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_postgres_artifacts.py -q`; retain output in `artifacts/logs/task-2997-tm-postgres-artifacts.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_atomic_publish` | Crash after blob write leaves an orphan; rollback never leaves an index referencing unavailable bytes or a journal-only registration. |
| `test_alias_concurrency` | Concurrent writers produce distinct versions with one consistent current alias and old evidence intact. |
| `test_pins_restart` | Cross-task evidence survives producer terminal state and restart; every lookup checks trusted scope. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2997-tm-postgres-artifacts.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

Not completed. The implementing agent records completed-by, date, verification evidence, notes, and any approved deviations here when acceptance passes.
