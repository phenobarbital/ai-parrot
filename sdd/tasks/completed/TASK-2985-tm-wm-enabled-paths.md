# TASK-2985: Route enabled working-memory operations and cap raw reads

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2977, TASK-2984
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: May run with ready disjoint tasks such as TASK-2986, TASK-2987, TASK-2988 after prerequisites. Owns distinct output files; do not modify package exports or shared fixtures outside this scope.
**Delivery**: A
**Spec acceptance**: AC5, AC6, AC13

---

## Context

Implements §2 Catalog Backend; ResultPolicy of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2977, TASK-2984 before implementation.

## Scope

- Add optional task-memory composition and route every enabled store/import/compute/merge/temporary/drop path through awaited catalog operations.
- Implement enabled ResultPolicy 2,000,000-byte ceiling, lower-only caller limit, 0=never and tabular offset/limit pages without whole-table loading.
- Choose enabled result input schema only when configured; preserve legacy schemas, AnswerMemory bridge and summary behavior otherwise.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/src/parrot/tools/working_memory/models.py` | MODIFY | Scoped implementation |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_enabled_working_memory.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.tools.working_memory import WorkingMemoryToolkit  # packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259
from pydantic import BaseModel, Field  # packages/ai-parrot/src/parrot/tools/working_memory/models.py:7
from parrot.tools.working_memory.internals import WorkingMemoryCatalog, CatalogEntry, GenericEntry  # packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542
from parrot.tools.toolkit import AbstractToolkit  # packages/ai-parrot/src/parrot/tools/toolkit.py:539
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259`**

```python
async def get_result(self, key: str, max_length: int = 500, include_raw: bool = False) -> dict:
```

Constructor at line 103 has session_id/max_rows/max_cols/tool_locals_registry/answer_memory/thread_offload_cells; store at 194 and store_result at 208 call synchronous catalog methods.

**`packages/ai-parrot/src/parrot/tools/working_memory/models.py:7`**

```python
# Existing input model at line 268:
class GetResultInput(BaseModel):
    key: str
    max_length: int
    include_raw: bool
```

OperationSpecInput begins at 104; GetResultInput default max_length=500 and include_raw=False. Existing Pydantic import is at line 7.

**`packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542`**

```python
def get(self, key: str) -> CatalogEntry | GenericEntry:
def drop(self, key: str) -> bool:
```

GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.

**`packages/ai-parrot/src/parrot/tools/toolkit.py:539`**

```python
def _generate_tools(self) -> None:
```

Only public coroutine methods are discovered; names starting with underscore and exclude_tools are skipped. Working-memory prefix is wm and store is already excluded.

### Does NOT Exist

- Task-memory opt-in constructor wiring and wm_* task tools do not exist at the verification commit.
- No task-memory Pydantic models or PlanChanges command union exists at this commit.
- No awaited catalog backend, versioned evidence metadata, locks or to_descriptor method exists at this commit.
- No automatic rule hides new public task methods merely because task_memory is unset.
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
- `packages/ai-parrot/src/parrot/tools/working_memory/models.py:7` — OperationSpecInput begins at 104; GetResultInput default max_length=500 and include_raw=False. Existing Pydantic import is at line 7.
- `packages/ai-parrot/src/parrot/tools/working_memory/internals.py:542` — GenericEntry at 70 owns data; CatalogEntry at 175 owns df and computed shape at 189. Catalog constructor at 468 and put/put_generic at 473/499 are synchronous and use a plain dictionary.
- `packages/ai-parrot/src/parrot/tools/toolkit.py:539` — Only public coroutine methods are discovered; names starting with underscore and exclude_tools are skipped. Working-memory prefix is wm and store is already excluded.

## Acceptance Criteria

- [ ] All existing enabled mutation routes publish version metadata once, including error/temporary paths.
- [ ] Exact-cap/multibyte/oversized pages enforce serialized and decoded limits and return no raw data on error.
- [ ] Legacy tool schemas and WM regression outputs are unchanged when task memory is absent.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC5, AC6, AC13 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_enabled_working_memory.py -q`; retain output in `artifacts/logs/task-2985-tm-wm-enabled-paths.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_write_routes` | All existing enabled mutation routes publish version metadata once, including error/temporary paths. |
| `test_raw_bounds` | Exact-cap/multibyte/oversized pages enforce serialized and decoded limits and return no raw data on error. |
| `test_disabled` | Legacy tool schemas and WM regression outputs are unchanged when task memory is absent. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-2985-tm-wm-enabled-paths.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: Claude Opus 5 (sdd-worker) — session `01WeeSf3QmPq58bBxturogRX`
**Date**: 2026-09-08
**Status**: done

### Evidence
- `test_enabled_working_memory.py` → **22 passed**.
  Log: `artifacts/logs/task-2985-tm-wm-enabled-paths.log`.
- **Regression evidence (AC13):** `tests/tools` + `tests/bots/flows/plan`
  give **1947 passed / 53 failed**, and the sorted `FAILED` list is
  **byte-identical** to unmodified `dev` — zero additions, zero removals.
- The one remaining `ruff` finding in `tool.py`
  (`F401 parrot.memory.AnswerMemory`) is pre-existing on baseline.

### AC13 is the point, and it is enforced structurally
- `task_memory=None` (the default) leaves every path on the legacy
  synchronous catalog, with the legacy schemas and the legacy raw-read
  behaviour.
- The enabled `wm_get_result` schema is a **separate model**
  (`EnabledGetResultInput`) chosen at **tool-generation time**, not extra
  fields bolted onto `GetResultInput`. That is what resolves the spec's
  own conflict between "cap raw reads" and "disabled behaviour
  byte-identical". A test asserts the disabled schema still has exactly
  `{key, max_length, include_raw}` and that the legacy model is untouched.
- `@tool_schema` stores the model on the **function**, shared by every
  instance, so the swap had to happen on the *generated tool object* —
  otherwise enabling one toolkit would silently change the schema of
  every other one in the process.

### Write routing
Three helpers (`_put`/`_put_generic`/`_drop`) rather than a branch at each
of the **twelve** call sites Phase 0 inventoried. With the decision in one
place, an enabled deployment cannot end up with a route that quietly
stayed synchronous and therefore unversioned.

That is *verified*, not assumed: the catalog raises
`SyncCatalogWriteError` on a synchronous write when a backend is
attached, so a missed route fails loudly instead of silently producing
unrecoverable evidence.

`test_write_routes` checks that a **version landed in the backend**, not
that a helper was called — the latter would pass against a route that
published nothing.

### Raw-read policy (enabled only)
1. **Two ceilings, both enforced**: the *serialized* size of the response
   and, for tabular values, the *decoded* page size.
2. **An over-limit response carries no raw payload** and points at
   `wm_compute_and_store`. The check happens **before** the payload is
   attached — truncating an opaque `repr` after loading it has already
   paid the cost the ceiling exists to avoid.
3. **The configured ceiling is hard**: a caller may lower it but never
   raise it, and `0` means never. Tested by requesting 10 MB against a
   500-byte configuration and getting a refusal.
4. **Exact-cap boundary tested both ways** — at the cap passes, one byte
   over refuses.
5. **Multibyte is measured in bytes.** A 3-byte-per-character payload is
   refused where a character-based check would have let it through.
6. **A small page of a 2,000-row value stays readable** while the whole
   value is refused — which is the entire point of paging.

### Mistakes worth recording
Two more API guesses of mine were wrong and were corrected against the
real source rather than worked around: `compute_and_store` takes an
`OperationSpecInput` `spec` (not `code`/`store_as`/`inputs`), and `store`
returns `{"status", "summary"}` rather than a flat dict. Together with
TASK-2984's three, that is five guessed signatures caught by running the
tests against real objects — a good argument for never asserting against
a stand-in here.
