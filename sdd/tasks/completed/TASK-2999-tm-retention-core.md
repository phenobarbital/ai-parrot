# TASK-2999: Implement deterministic retention decisions and in-memory sweeping

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2976, TASK-2978, TASK-2980
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2981, TASK-2982, TASK-2983 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC5, AC7, AC12

---

## Context

Implements §2 Retention and Redaction of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2976, TASK-2978, TASK-2980 before implementation.

## Scope

- Implement pure due-action selection and idempotent RetentionSweeper.run_once with injected clock and event-first mutation.
- Apply 7-day inactivity pause, 30 days from inactivity pause to abandonment, terminal/stale artifact rules and bounded capacity reserves.
- Honor cross-task evidence pins, record forced in-memory invalidation/tombstones and keep recall reads from resetting activity.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/retention.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_retention_core.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.tools.working_memory.internals import WorkingMemoryCatalog, CatalogEntry, GenericEntry  # packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542
from parrot.memory.compaction.omission import OmissionStore  # packages/ai-parrot/src/parrot/memory/compaction/omission.py:61
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

**`packages/ai-parrot/src/parrot/memory/compaction/omission.py:61`**

```python
async def put(self, session_key: str, content: str, *, turn_id: Optional[str] = None) -> str:
# get at line 87:
async def get(self, session_key: str, content_id: str) -> Optional[str]:
```

InMemoryOmissionStore begins at 120, RedisOmissionStore at 149. get fetches payload text; built-in IDs already include one om_ prefix.

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
- No bounded availability-probe API exists; custom stores need a backward-compatible unknown fallback.
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
- `packages/ai-parrot/src/parrot/memory/compaction/omission.py:61` — InMemoryOmissionStore begins at 120, RedisOmissionStore at 149. get fetches payload text; built-in IDs already include one om_ prefix.
- `packages/ai-parrot/src/parrot/tools/working_memory/models.py:7` — OperationSpecInput begins at 104; GetResultInput default max_length=500 and include_raw=False. Existing Pydantic import is at line 7.

## Acceptance Criteria

- [ ] Boundary tests distinguish inactivity, paused-for-inactivity duration and terminal retention anchors.
- [ ] Forced no-tier eviction invalidates evidence explicitly; pinned supported data prefers spill.
- [ ] Repeated run_once creates no duplicate state transition and maintenance capacity remains bounded.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC5, AC7, AC12 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_retention_core.py -q`; retain output in `artifacts/logs/task-2999-tm-retention-core.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_clock_rules` | Boundary tests distinguish inactivity, paused-for-inactivity duration and terminal retention anchors. |
| `test_pin_eviction` | Forced no-tier eviction invalidates evidence explicitly; pinned supported data prefers spill. |
| `test_idempotent_sweep` | Repeated run_once creates no duplicate state transition and maintenance capacity remains bounded. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2999-tm-retention-core.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker, delegated fork) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence
- `test_retention_core.py` → **29 passed**, all three required cases
  present (`test_clock_rules`, `test_pin_eviction`,
  `test_idempotent_sweep`). Committed suite unaffected.
  Log: `artifacts/logs/task-2999-tm-retention-core.log`.
- `ruff`/`black`/`isort` clean.

### The design trap — verified independently during review
Abandonment anchors on the **pause event**, not on `updated_at`.
Anchoring on `updated_at` would be a bug **that hides itself**: the
sweeper's own `retention_scheduled` intent bumps `updated_at`, so the
sweeper would perpetually reset the very clock it was measuring and
nothing would ever be cancelled.

Confirmed directly: a sweeper event at `T0 + 40d` moved `updated_at` from
`T0` to `T0 + 40d` while leaving `revision` untouched (it is an
*immaterial* event under TASK-2974's identity rule). `_anchors()`
therefore excludes `Actor.SWEEPER` events from "activity" entirely, and
`test_clock_rules_sweeper_own_events_are_not_activity` pins **both**
halves — the anchor does not move, *and* `updated_at` demonstrably did.

### Design decisions
1. **Selection is pure and separated from effects.**
   `select_due_tasks`/`select_due_artifacts`/`select_due_blobs` take an
   injected `now` plus immutable views; an AST check asserts they call no
   clock, no randomness and no I/O.
2. **Destructive capabilities are Protocols the host wires**
   (`ArchiveWriter`, `JournalPurge`, `BlobSweeper`). Delivery A ships
   in-memory artifact sweeping only. A missing capability **defers with a
   reason**, never a silent skip — a test asserts the task survives.
3. **Three independent artifact protections**: non-terminal evidence is
   protected regardless of age; **any** pin defers, including a
   **cross-task** pin (the case a naive "is the owner done?" check gets
   wrong); current versions follow the 90-day rule, not the 24-hour one.
4. **Archive must succeed AND verify before deletion**, tested in three
   stages — write fails, write succeeds but verification fails, then
   success — with the task asserted to survive the first two. The archive
   is also asserted to **contain** the retention event, since deleting
   the journal destroys the only other copy.
5. **Retry does not re-announce.** `_announce` suppresses a duplicate
   trailing intent, so a repeatedly-failing archive cannot grow the
   journal. Asserted over three retries.
6. **Idempotence is structural, not bookkept** — each action changes the
   state that made it due.

### Honest limitation, documented rather than papered over
The injected clock does **not** control the *service's* transition
timestamps: `TaskMemoryService._event` stamps `utc_now()`, so only the
sweeper's own intent events follow the injected clock. In production both
are wall time and agree; in tests the abandonment boundary is therefore
computed from the journal's actual pause event rather than from the test
clock. Making it fully injectable would mean changing `service.py`, which
this task does not own. **A reasonable follow-up.**

### Contract note
All three listed anchors (`internals.py:542`, `omission.py:61`,
`models.py:7`) exist but are **irrelevant** — this task consumes none of
them. It works against `config.py`, `models.py`, `store/memory.py`,
`artifacts.py` and `service.py`, none of which the contract mentions.
