# TASK-2989: Expose enabled task command, selection and recall tools

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2980, TASK-2985, TASK-2988
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2991, TASK-2992, TASK-2993 after prerequisites. Shared-file predecessors: TASK-2985; do not edit their files concurrently.
**Delivery**: A
**Spec acceptance**: AC1, AC7, AC10, AC11, AC13

---

## Context

Implements §2 New Public Interfaces of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2980, TASK-2985, TASK-2988 before implementation.

## Scope

- Expose all ten wm_* tools with explicit Pydantic input schemas and docstrings through private TaskMemory composition.
- Wire begin/update-plan/update-step/decision/hint/recall/events/artifacts/select/update-task, compact errors and bounded cursor responses.
- Publish successful running-step declarations to the turn session; infer omitted task IDs only from validated association and hide all new tools when disabled.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py` | CREATE | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/working_memory/__init__.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_task_tools.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.tools.working_memory import WorkingMemoryToolkit  # packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259
from parrot.tools.toolkit import AbstractToolkit  # packages/ai-parrot/src/parrot/tools/toolkit.py:539
from parrot.tools.working_memory import WorkingMemoryToolkit  # packages/ai-parrot/src/parrot/tools/working_memory/__init__.py:2
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259`**

```python
async def get_result(self, key: str, max_length: int = 500, include_raw: bool = False) -> dict:
```

Constructor at line 103 has session_id/max_rows/max_cols/tool_locals_registry/answer_memory/thread_offload_cells; store at 194 and store_result at 208 call synchronous catalog methods.

**`packages/ai-parrot/src/parrot/tools/toolkit.py:539`**

```python
def _generate_tools(self) -> None:
```

Only public coroutine methods are discovered; names starting with underscore and exclude_tools are skipped. Working-memory prefix is wm and store is already excluded.

**`packages/ai-parrot/src/parrot/tools/working_memory/__init__.py:2`**

```python
# Existing public export:
WorkingMemoryToolkit
```

Package exports existing WM models and GenericEntry but not catalog/task-memory backend classes.

### Does NOT Exist

- Task-memory opt-in constructor wiring and wm_* task tools do not exist at the verification commit.
- No automatic rule hides new public task methods merely because task_memory is unset.
- No TaskMemoryConfig or task-tool service export exists; exports must remain lazy where appropriate.
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

- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259` — Constructor at line 103 has session_id/max_rows/max_cols/tool_locals_registry/answer_memory/thread_offload_cells; store at 194 and store_result at 208 call synchronous catalog methods.
- `packages/ai-parrot/src/parrot/tools/toolkit.py:539` — Only public coroutine methods are discovered; names starting with underscore and exclude_tools are skipped. Working-memory prefix is wm and store is already excluded.
- `packages/ai-parrot/src/parrot/tools/working_memory/__init__.py:2` — Package exports existing WM models and GenericEntry but not catalog/task-memory backend classes.

## Acceptance Criteria

- [ ] Exactly intended enabled task tools appear; no internal service methods leak and wm_store remains excluded.
- [ ] Every public command reaches its scoped service; completion and selection retain typed failure semantics.
- [ ] Recall/list tools neither append journal entries nor select/mutate tasks implicitly.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC1, AC7, AC10, AC11, AC13 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_task_tools.py -q`; retain output in `artifacts/logs/task-2989-tm-task-tools.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_schemas` | Exactly intended enabled task tools appear; no internal service methods leak and wm_store remains excluded. |
| `test_commands` | Every public command reaches its scoped service; completion and selection retain typed failure semantics. |
| `test_readonly` | Recall/list tools neither append journal entries nor select/mutate tasks implicitly. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2989-tm-task-tools.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: sdd-worker (Claude Opus 5) — 2026-09-08
**Commit**: `736191198`

### What was built

The ten `wm_*` tools of spec §2, with explicit Pydantic input schemas
bound via `@tool_schema`, wrapping `TaskMemoryService` through a private
`TaskMemory` composition root (config, scope, stores, service,
`RecallReader`, selected-task association). `TaskMemoryToolsMixin` is
mixed into `WorkingMemoryToolkit`; when `task_memory is None` the
constructor adds `TASK_TOOL_METHODS` to the **instance** `exclude_tools`,
which `_generate_tools` already honours.

### Verification evidence

- `test_task_tools.py`: 6 passed (`test_schemas`, `test_commands`,
  `test_readonly`, plus scope-binding, implicit-selection and
  budget-refusal cases). Log: `artifacts/logs/task-2989-tm-task-tools.log`.
- `tests/tools/working_memory`: **801 passed, 62 skipped, 0 failed**.
- **AC13 checked structurally, not asserted**: the disabled toolkit's
  tool names *and* every input schema's field set were dumped from
  `dev`'s source tree and from `HEAD` and diffed — identical.
- `tests/tools` (excl. working_memory): FAILED-set is a strict subset of
  the `dev` baseline. All 52 remaining failures are pre-existing and
  unrelated (`databasequery`, `test_auto_registration_hooks`).
- `ruff check` clean on all four owned files. The one F401 in `tool.py`
  (`AnswerMemory` under `TYPE_CHECKING`) was verified to exist on `dev`
  and was left alone as out of scope.

### Corrections made during implementation

Five API assumptions were caught by reading source before use, each of
which would have shipped a defect:

1. **`read_recall` does not exist.** Recall's I/O half is
   `RecallReader.recall(scope, task_id, ...)`, which already resolves an
   omitted id and produces the bounded `needs_task_selection` page. The
   hand-rolled resolver drafted first was deleted in favour of it.
2. **`PlanChange` is a discriminated union on `op`.** The hand-written
   dict→model translator drafted first was both redundant and *lossy* —
   it silently dropped `update_constraint`. Replaced with
   `PlanChanges.model_validate`, so the parse and the "is this a real
   operation?" check are the same step and cannot drift from the models.
3. **The association protocol is wider than `resolve`.** An invented
   `_SelectionAssociation` adapter passed to `RecallReader` blew up on
   `recall_key`. There is a real `association.py` (`TaskAssociationStore`);
   `TaskMemory` now accepts one optionally and passes it straight through.
4. **`ResumeHint.text`, not `.next_action`** — the service *parameter* is
   `next_action` but the stored field is `text`.
5. **The recall snapshot is flat** — `snapshot["task_id"]`, not
   `snapshot["task"]["task_id"]`.

### Notes for the reviewer

- **Delivery A remains non-durable.** `TaskMemory.select()` is in-process
  only (turn session + local). Persisting to the durable association is a
  separate awaitable step (`persist_selection` / `release_selection`)
  that no-ops when no `TaskAssociationStore` is wired, and whose failure
  is reported as `association_durable: false` rather than raised — a
  committed task must never be lost because its association could not be
  written.
- **`select()` happens only after the append commits**, so a rejected
  creation never leaves a selection pointing at a task that does not
  exist. Likewise `session.declare(step_id)` runs only after a *successful*
  running transition.
- A prior claim in `tool.py` that the disabled path "never pulls in
  task_memory at all" became false once the mixin was inherited (it must
  be, for the methods to be discoverable). The comment was corrected
  rather than left standing; `task_memory` imports only core dependencies
  (`orjson`, `pydantic`), so no new dependency reaches a disabled install.

### Approved deviations

None.
