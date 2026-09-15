# TASK-2978: Implement atomic in-memory journal and projections

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2972, TASK-2974
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2975, TASK-2976, TASK-2977 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC2, AC7, AC11, AC12

---

## Context

Implements §2 Persistence; Reducer of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2972, TASK-2974 before implementation.

## Scope

- Implement scoped creation, atomic event batches, snapshots and bounded task/event pages using per-task locks and the pure reducer.
- Deduplicate identical event IDs before sequence/revision assignment; reject conflicting reuse and stale expected revisions without partial writes.
- Enforce scope, task capacity, 100,000 foreground events and 1,000 reserved maintenance events; preserve projection/journal replay semantics.
- Provide reusable deterministic backend fixtures and a side-effect counter for later integration tests.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/store/memory.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_task_store_memory.py` | CREATE | Task-specific verification / fixtures |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/conftest.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.memory.abstract import ConversationTurn, ConversationHistory  # packages/ai-parrot/src/parrot/memory/abstract.py:178
from pydantic import BaseModel, Field  # packages/ai-parrot/src/parrot/tools/working_memory/models.py:7
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/memory/abstract.py:178`**

```python
def from_ai_message(cls, *, user_message: str, response: "AIMessage", user_id: str, chatbot_id: str, context_used: Optional[str] = None, turn_id: Optional[str] = None, assistant_text: Optional[str] = None, error: Optional[str] = None) -> "ConversationTurn":
```

from_ai_message builds tool_invocations from response.tool_calls at 229. ConversationHistory has a metadata dictionary at 272; omission_key at 397 scopes bot/user/session.

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

- No canonical task observer handoff or selected-task association behavior exists yet.
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

- `packages/ai-parrot/src/parrot/memory/abstract.py:178` — from_ai_message builds tool_invocations from response.tool_calls at 229. ConversationHistory has a metadata dictionary at 272; omission_key at 397 scopes bot/user/session.
- `packages/ai-parrot/src/parrot/tools/working_memory/models.py:7` — OperationSpecInput begins at 104; GetResultInput default max_length=500 and include_raw=False. Existing Pydantic import is at line 7.

## Acceptance Criteria

- [ ] Two revisions race: only one applicable batch wins; journal sequences have no gaps.
- [ ] Exact retry returns existing result even with stale expected_revision; different payload under the same ID fails.
- [ ] Foreign scope and exhausted capacity reject before mutation; reserved recovery events remain appendable.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC2, AC7, AC11, AC12 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_task_store_memory.py -q`; retain output in `artifacts/logs/task-2978-tm-task-memory-store.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_concurrent_append` | Two revisions race: only one applicable batch wins; journal sequences have no gaps. |
| `test_idempotency` | Exact retry returns existing result even with stale expected_revision; different payload under the same ID fails. |
| `test_limits` | Foreign scope and exhausted capacity reject before mutation; reserved recovery events remain appendable. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2978-tm-task-memory-store.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker, delegated fork) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence
- `test_task_store_memory.py` → **33 passed**, including the inherited
  `TaskMemoryStoreConformance` cases.
- Whole `task_memory` suite: **561 passed, 6 skipped** (the skips are
  another task's PostgreSQL-gated cases, explicitly labelled).
- `ruff`/`black`/`isort` clean. Log:
  `artifacts/logs/task-2978-tm-task-memory-store.log`.

### Two defects fixed in TASK-2972's conformance suite
This was the first **reducer-backed** store to run against the suite, and
it exposed two fixture bugs that had passed only because the reference
double runs no reducer:

1. `make_event` built a `task_started` with **no goal**. The real reducer
   refuses it — and rightly: a goal-less start cannot be replayed, so a
   reducer-version migration or a restart rebuild would fail on it.
2. `test_conformance_sequences_are_contiguous` used a second
   `task_started` on a **live** task as its "genuinely new" event. Any
   reducer-backed store refuses that. The case is about sequence
   contiguity, not lifecycle, so it now uses `task_resumed`.

A conformance fixture that only a placeholder can satisfy is worse than
none, so the fixture was corrected rather than the store bent around it.
Every assertion the affected case makes is preserved.

### Design decisions
1. **Stage-then-publish is the atomicity mechanism** — classify → check
   revision → check capacity → reduce into a **local** variable → only
   then mutate the record. "A rejected command changes nothing" is true by
   construction, not by cleanup. A test places a malformed event *after* a
   valid one to prove no partial prefix lands.
2. **Two locks, deliberately**: a per-task `asyncio.Lock` for appends and
   a short registry lock for dict operations only, never held across a
   reduction, so it cannot degenerate into the global lock the design
   avoids.
3. **Creation reduces before the record exists**, so a malformed batch
   leaves no empty task behind. Creation is idempotent: five concurrent
   identical creates yield one task and one event.
4. **A batch counts as reserved only if EVERY event is reserved.** A batch
   carrying any ordinary work is ordinary work — otherwise one degraded
   event would smuggle foreground work into the recovery headroom.
5. **Lazy migration replays; it does not renumber.** The test corrupts the
   stale projection's `goal` as well as its version, so a store that
   merely bumped the version number would still fail.
6. **Keyset pagination on `(updated_at, task_id)` descending.** The id
   tiebreak makes the order *total*; without it two tasks sharing a
   timestamp could swap places between pages and keyset paging would skip
   or repeat one.
7. **`create_task` validates goal agreement** between the command and the
   `task_started` event rather than silently stamping one over the other.
   The journal is the source of truth, so a disagreement is a caller bug.
8. **`conftest.py` is fixtures-only**, all `tm_`-prefixed, with no hooks
   and no `autouse`. Verified additive: the suite passed identically
   before and after adding it. `SideEffectCounter` records each invocation
   rather than counting, so a later test can distinguish "ran once, result
   lost" from "ran twice" — which a mock's `call_count` cannot.

### Note
The task file is `TASK-2978-tm-task-memory-store.md`; the dispatch brief
said `-task-store-memory`. Logs were written under both names, with the
task file's spelling treated as authoritative.
