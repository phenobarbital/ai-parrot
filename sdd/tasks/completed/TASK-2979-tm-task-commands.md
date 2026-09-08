# TASK-2979: Implement task, plan, decision and hint commands

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2977, TASK-2978
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2981, TASK-2982, TASK-2987 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC1, AC2, AC7, AC11

---

## Context

Implements §2 Public Interfaces; Reducer of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2977, TASK-2978 before implementation.

## Scope

- Implement TaskMemory task creation, plan changes, lifecycle updates, decisions, hints and read query facade over injected stores.
- Assign runtime IDs, resolve request-local labels, validate all command batches, and return typed compact conflict/limit errors.
- Keep terminal tasks immutable, retain superseded evidence and expose plan-incomplete state; exclude tool exposure and completion validators from this task.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/service.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_task_commands.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.tools.working_memory.internals import WorkingMemoryCatalog, CatalogEntry, GenericEntry  # packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542
from parrot.memory.abstract import ConversationTurn, ConversationHistory  # packages/ai-parrot/src/parrot/memory/abstract.py:178
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542`**

```python
def get(self, key: str) -> CatalogEntry | GenericEntry:
def drop(self, key: str) -> bool:
```

GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.

**`packages/ai-parrot/src/parrot/memory/abstract.py:178`**

```python
def from_ai_message(cls, *, user_message: str, response: "AIMessage", user_id: str, chatbot_id: str, context_used: Optional[str] = None, turn_id: Optional[str] = None, assistant_text: Optional[str] = None, error: Optional[str] = None) -> "ConversationTurn":
```

from_ai_message builds tool_invocations from response.tool_calls at 229. ConversationHistory has a metadata dictionary at 272; omission_key at 397 scopes bot/user/session.

### Does NOT Exist

- No awaited catalog backend, versioned evidence metadata, locks or to_descriptor method exists at this commit.
- No canonical task observer handoff or selected-task association behavior exists yet.
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
- `packages/ai-parrot/src/parrot/memory/abstract.py:178` — from_ai_message builds tool_invocations from response.tool_calls at 229. ConversationHistory has a metadata dictionary at 272; omission_key at 397 scopes bot/user/session.

## Acceptance Criteria

- [ ] Begin, replan, pause/resume/cancel, decisions and hints produce expected typed events and revisions.
- [ ] Cycle/missing dependency/stale revision leaves journal and projection unchanged.
- [ ] Scope is runtime-owned and explicit task IDs do not permit crossing a scope.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC1, AC2, AC7, AC11 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_task_commands.py -q`; retain output in `artifacts/logs/task-2979-tm-task-commands.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_command_flow` | Begin, replan, pause/resume/cancel, decisions and hints produce expected typed events and revisions. |
| `test_rejected_batch` | Cycle/missing dependency/stale revision leaves journal and projection unchanged. |
| `test_identity` | Scope is runtime-owned and explicit task IDs do not permit crossing a scope. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2979-tm-task-commands.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence
- `uv run pytest .../test_task_commands.py -q` → **23 passed**.
  Log: `artifacts/logs/task-2979-tm-task-commands.log`.
- `ruff`/`black --line-length 120 --target-version py312`/`isort` clean.
- Exercised against the **real** in-memory store and the **real** reducer,
  not a mock. A mocked store would have let the service claim an
  atomicity it never actually demonstrated.

### Acceptance mapping

| Criterion | Evidence |
|---|---|
| Begin/replan/pause/resume/cancel/decisions/hints produce expected typed events and revisions | `test_command_flow_*` (8 cases) — event *kinds and order* asserted from the journal, not just the projection |
| Cycle / missing dependency / stale revision leaves journal and projection unchanged | `test_rejected_batch_*` (6 cases), each via `_assert_unchanged`, which compares projection, sequence AND event count |
| Scope is runtime-owned; explicit task ids cannot cross a scope | `test_identity_*` (5 cases), varying each scope component independently |
| AC1 | Begin → replan → complete flow restores runtime ids and ready work |
| AC2 | Service is store-agnostic; both backends are behaviourally identical by construction |
| AC7 | Supersession retains history; completion gate walks plan-incomplete → required-outstanding → success |
| AC11 | Structural check that no method accepts a scope component; `TaskNotFound` is not an existence oracle |

### Design decisions worth flagging downstream

1. **Runtime ids are minted here, never accepted.** A model-authored step
   id would let one task's command name another task's step. Asserted:
   two tasks built from the *same* labels get disjoint step ids.
2. **Labels resolve before anything is appended.** A malformed initial
   plan creates **no task at all** — asserted by checking the scope's task
   list is still empty after three different rejection modes.
3. **Batch validation runs against the RESULTING plan**, not per
   operation. That is what catches a cycle only two operations together
   would create, and a test builds exactly that case.
4. **`begin_task` commits `task_started` and `plan_updated` together**, so
   there is no window in which a task exists with a half-built plan.
5. **`TaskNotFound` is deliberately indistinguishable** between "belongs
   to another scope" and "does not exist". A test asserts both the type
   and that neither message says "forbidden" or "another".
6. **`update_step` records, it does not judge.** Completion validators
   (TASK-2980) supply `completion_source` and `validator_results`; this
   layer passes them through for replay to consume rather than deciding
   whether evidence justifies a completion.
7. **`expected_revision` is required for plan/step/lifecycle changes but
   optional for decisions.** A decision does not conflict with concurrent
   work the way a plan revision does.
8. **Completion is still gated by the reducer**, not re-implemented here —
   the service cannot be used to bypass the plan-complete or
   required-steps checks.
9. **`compact_state` is deliberately tiny** — a command acknowledgement
   should let the caller issue its next command, not re-deliver the task.
   A test asserts the exact key set and that `goal`/`steps` are absent.

### Environment incident during this task (not a code defect)
Mid-task the shared `.venv` was pruned by a concurrent process: `pytest`,
`pytest-asyncio`, `black`, `isort`, `ruff` and **seven of the nine
workspace distributions** (including `ai-parrot-server`, which owns
`parrot.mcp.transports`) disappeared, so the suite failed to collect. This
is the documented shared-venv hazard. Restored by reinstalling the dev
tools and re-installing each workspace package editable with `--no-deps`
(to avoid another resolution pass). All results above were produced after
the restore.
