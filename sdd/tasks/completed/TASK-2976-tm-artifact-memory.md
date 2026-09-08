# TASK-2976: Implement scoped versioned in-memory artifact backend

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2972, TASK-2975
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2973, TASK-2974, TASK-2978 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC5, AC6, AC11, AC12

---

## Context

Implements §2 Catalog Backend; Retention of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2972, TASK-2975 before implementation.

## Scope

- Implement InMemoryArtifactStore with scoped task aliases, atomic versions, tombstones, immutable snapshots and descriptors for both entry kinds.
- Implement bounded version loads and page reads, byte-accounted 512 MiB LRU, cross-task evidence pins and optional spill protocol.
- Expose explicit invalidation events/receipts when pinned bytes cannot be retained; never silently present expired data as verified.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/artifacts.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_artifact_memory.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.tools.working_memory.internals import WorkingMemoryCatalog, CatalogEntry, GenericEntry  # packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542
from pydantic import BaseModel, Field  # packages/ai-parrot/src/parrot/tools/working_memory/models.py:7
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542`**

```python
def get(self, key: str) -> CatalogEntry | GenericEntry:
def drop(self, key: str) -> bool:
```

GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.

**`packages/ai-parrot/src/parrot/tools/working_memory/models.py:7`**

```python
# Existing input model at line 268:
class GetResultInput(BaseModel):
    key: str
    max_length: int
    include_raw: bool
```

OperationSpecInput begins at 104; GetResultInput default max_length=500 and include_raw=False. Existing Pydantic import is at line 7.

### Does NOT Exist

- No awaited catalog backend, versioned evidence metadata, locks or to_descriptor method exists at this commit.
- No task-memory Pydantic models or PlanChanges command union exists at this commit.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

Compose the service/backend contracts from completed prerequisites. Keep new methods private unless the spec explicitly lists an LLM-facing tool. Keep the disabled path behavior and schemas unchanged.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542` — GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.
- `packages/ai-parrot/src/parrot/tools/working_memory/models.py:7` — OperationSpecInput begins at 104; GetResultInput default max_length=500 and include_raw=False. Existing Pydantic import is at line 7.

## Acceptance Criteria

- [ ] Concurrent overwrite/drop/recreate preserves unique monotonic versions and old evidence.
- [ ] Foreign scopes cannot read versions; multiple task pins prevent silent eviction.
- [ ] Capacity includes snapshots/live retained bytes and bounded loads cannot exceed their ceiling.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC5, AC6, AC11, AC12 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_artifact_memory.py -q`; retain output in `artifacts/logs/task-2976-tm-artifact-memory.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_alias_race` | Concurrent overwrite/drop/recreate preserves unique monotonic versions and old evidence. |
| `test_scope_pins` | Foreign scopes cannot read versions; multiple task pins prevent silent eviction. |
| `test_lru` | Capacity includes snapshots/live retained bytes and bounded loads cannot exceed their ceiling. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2976-tm-artifact-memory.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker, delegated fork) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence
- `test_artifact_memory.py` → **42 passed**, including all 9 inherited
  `ArtifactStoreConformance` cases and the three required cases
  (`test_alias_race`, `test_scope_pins`, `test_lru`).
- Whole suite: **448 passed**. Log: `artifacts/logs/task-2976-tm-artifact-memory.log`.
- `ruff` (incl. F401/F811/E501) clean; `black`/`isort` applied.
- Contract re-verified; **no stale anchors**. Verified independently:
  `isinstance(store, ArtifactStore)` is `True`.

### A design hole found and closed — REVIEW THIS
The spec requires an invalidation receipt when pinned evidence cannot be
retained. As first written that path was **unreachable dead code**:
capacity is enforced at the end of `put`, and the version being registered
is not pinned yet, so the newcomer is always the eviction victim and
evicting it always restores an already-within-budget state. Pinned
evidence could never be reached.

Fixed with `put(..., pin_for=task_id)`, which registers and pins
atomically so a new version competes for retention on equal terms with
existing pinned evidence.
`test_scope_pins_a_late_pin_cannot_protect_an_evicted_newcomer` pins the
hazard explicitly so the atomic form cannot later be dropped as
"redundant". This adds one keyword-only optional parameter beyond the
protocol signature; conformance is unaffected.

### Other decisions
1. **Drop/recreate continues the version counter.** The tombstone keeps
   `latest_version`, so a re-`put` after `drop_alias` yields `@3`, never
   `@1` again — a fresh value cannot shadow still-pinned evidence at the
   same coordinates.
2. **Three snapshot outcomes, three treatments.** `CAPTURED` → independent
   accounted copy, may be verifiable. `SPILL_REQUIRED` → `persisted` with
   a durable tier, else `missing` + unverifiable (Delivery A cannot
   promise retained bytes). `UNVERIFIABLE` → retained as a **live
   reference**, not a copy: usable as working memory, never as evidence.
3. **Live references are byte-accounted** — holding one keeps the object
   alive, so reporting zero would understate residency.
4. **Explicit `evict` does not invalidate; capacity-driven eviction of
   *pinned* evidence does.** A caller asking for bytes back is not the
   same event as evidence being sacrificed.
5. **Tabular paging measures the page, not the table.** A 5,000-row frame
   over the ceiling still yields a 5-row page; an over-ceiling *page* is
   refused rather than trimmed.
6. **`get_version(..., task_id=X)` refuses same-scope cross-task
   versions.** Scope alone authorizes only when no task filter is given.
7. **Receipts are drained via `drain_receipts()`**, not pushed through a
   callback — this module owns no journal and must not acquire one.

It deliberately imports none of `CatalogEntry`/`GenericEntry`/
`WorkingMemoryCatalog` despite their presence in the task's contract: it
sits *behind* the catalog (D1) and takes payloads as `Any`, so coupling it
to the legacy entry classes would invert the dependency.
