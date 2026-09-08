# TASK-3002: Verify in-process continuity and disabled compatibility

**Feature**: FEAT-538 - Recoverable Task Memory for WorkingMemoryToolkit
**Spec**: `sdd/specs/workingmemory-toolkit.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2990, TASK-2991, TASK-2993, TASK-2999
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Serial verification gate: wait for all dependencies and run without concurrent edits to production files exercised by the checks.
**Delivery**: A
**Spec acceptance**: AC1, AC3, AC4, AC5, AC6, AC7, AC10, AC11, AC13, AC14

---

## Context

Implements §4 Primary continuity; Delivery A of the approved specification. Delivery A establishes in-process continuity and must not be advertised as durable. Consume the committed contracts from TASK-2990, TASK-2991, TASK-2993, TASK-2999 before implementation.

## Scope

- Implement the four-step primary scenario with synthetic dataset, one validated and one asserted completion, recoverable failure, context loss and explicit-ID recall.
- Assert preserved constraints/version refs and next ready step with no repeated physical work; cover multi-task selection and in-process worker replacement.
- Run focused WM/manager/plan/compaction/worker regressions and byte/schema parity with task memory disabled; document A as non-durable.

**NOT in scope**: Other task deliverables and files not listed here; provider/client schema changes, unrelated refactors, and new dependencies. Later-task APIs may be represented by explicit protocol fixtures, never runtime stubs shipped as complete implementations.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_delivery_a.py` | CREATE | Task-specific verification / fixtures |
| `packages/ai-parrot/tests/tools/working_memory/task_memory/test_disabled_compatibility.py` | CREATE | Task-specific verification / fixtures |

Ownership includes only these files and this task's SDD status/completion fields. You are not alone in the codebase: preserve others' edits and coordinate changes to shared files. CREATE refers to new feature outputs; MODIFY may reference a file created by an earlier dependency.

## Codebase Contract (Anti-Hallucination)

Re-read against core source at `0b4920b2f` on 2026-09-08. The core source tree is unchanged from the spec's pinned implementation commit; task artifacts do not implement the new APIs.

### Verified Imports

```python
from parrot.tools.working_memory import WorkingMemoryToolkit  # packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259
from parrot.bots.abstract import AbstractBot  # packages/ai-parrot/src/parrot/bots/abstract.py:1742
from parrot.bots.flows.plan.node import PlanToolNode, build_manifest  # packages/ai-parrot/src/parrot/bots/flows/plan/node.py:347
from parrot.tools.repl_worker.handle import WorkerHandle  # packages/ai-parrot/src/parrot/tools/repl_worker/handle.py:1036
```

### Existing Signatures to Use

Signature/field excerpts below identify existing APIs, not runnable replacement implementations.

**`packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259`**

```python
async def get_result(self, key: str, max_length: int = 500, include_raw: bool = False) -> dict:
```

Constructor at line 103 has session_id/max_rows/max_cols/tool_locals_registry/answer_memory/thread_offload_cells; store at 194 and store_result at 208 call synchronous catalog methods.

**`packages/ai-parrot/src/parrot/bots/abstract.py:1742`**

```python
async def render_context_history(self, history: Optional[ConversationHistory]) -> Tuple[List[HistoryMessage], Optional[CompactionResult]]:
# save_conversation_turn at line 1909:
async def save_conversation_turn(self, user_id: str, session_id: str, turn: ConversationTurn, *, compaction: Optional[CompactionCommit] = None) -> None:
```

Rendering returns messages plus CompactionResult at 1793; memory_key_id at 1864 is the stable identity and save_conversation_turn remains the sole writer.

**`packages/ai-parrot/src/parrot/bots/flows/plan/node.py:347`**

```python
async def _store(self, key: str, payload: Any, *, index: Optional[int]) -> int:
# _call_with_retry at line 414:
async def _call_with_retry(self, args: Dict[str, Any]) -> Any:
```

_call_with_retry dispatches through the manager at 431; _store awaits store_result at 350 after dispatch returns. _read_key at 392 accesses catalog.get synchronously. Factory closure starts around 530.

**`packages/ai-parrot/src/parrot/tools/repl_worker/handle.py:1036`**

```python
async def inject_dataframe(self, name: str, df: Any) -> None:
# set_var at line 1092:
async def set_var(self, name: str, value: Any) -> None:
```

Injection calls encode_dataframe in an executor and releases shared memory after acknowledgment; namespace APIs include get_var/snapshot/reset at 1087/1103/1108.

### Does NOT Exist

- Task-memory opt-in constructor wiring and wm_* task tools do not exist at the verification commit.
- No task recall injection/turn-task context helper exists in the current bot.
- No plan node ID automatically equals a runtime TaskStep ID; no receipt persists beyond dispatcher context reset yet.
- No strict evidence mode or generation-bound ReplBindingResolver exists.
- The new `parrot.tools.working_memory.task_memory` package and new interface contracts are absent at the verification commit. Dependencies in this task are responsible for introducing them; do not claim their proposed signatures are existing imports.

## Implementation Notes

### Pattern to Follow

Only these dedicated test files are writable; report production failures to their owning tasks rather than absorbing unrelated fixes.

### Key Constraints

- Use only the approved spec's semantics and defaults; no new dependencies, schema routing parameters, SQLite backend or autonomous retries.
- Existing imports above are verified at the recorded commit. New task-memory symbols are produced by prerequisites; read their committed definitions before importing them.
- Use strict type hints and Pydantic input models for new domain APIs; preserve existing dataclass serializers. Follow black/isort and inherited toolkit logging.
- Keep mutations atomic and scope-bound, heavy work off the event loop, and raw payloads/credentials out of recall and journal context.
- Log focused verification to artifacts/logs/. Re-run existing regressions relevant to touched shared files; service-gated tests must distinguish skipped from passed.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:259` — Constructor at line 103 has session_id/max_rows/max_cols/tool_locals_registry/answer_memory/thread_offload_cells; store at 194 and store_result at 208 call synchronous catalog methods.
- `packages/ai-parrot/src/parrot/bots/abstract.py:1742` — Rendering returns messages plus CompactionResult at 1793; memory_key_id at 1864 is the stable identity and save_conversation_turn remains the sole writer.
- `packages/ai-parrot/src/parrot/bots/flows/plan/node.py:347` — _call_with_retry dispatches through the manager at 431; _store awaits store_result at 350 after dispatch returns. _read_key at 392 accesses catalog.get synchronously. Factory closure starts around 530.
- `packages/ai-parrot/src/parrot/tools/repl_worker/handle.py:1036` — Injection calls encode_dataframe in an executor and releases shared memory after acknowledgment; namespace APIs include get_var/snapshot/reset at 1087/1103/1108.

## Acceptance Criteria

- [ ] One recall restores actionable state after deleting conversational context without replaying work.
- [ ] Error results, alias overwrite and mutable evidence have the correct distinct completion outcomes.
- [ ] Existing suites pass and disabled schema/output comparison shows no behavior drift.
- [ ] Scope is implemented without changes outside the ownership table, apart from required SDD status/completion updates.
- [ ] Spec criteria AC1, AC3, AC4, AC5, AC6, AC7, AC10, AC11, AC13, AC14 are verified for this task's scope and failure cases.
- [ ] Focused verification passes: `uv run pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_delivery_a.py packages/ai-parrot/tests/tools/working_memory/task_memory/test_disabled_compatibility.py -q`; retain output in `artifacts/logs/task-3002-tm-delivery-a.log`.
- [ ] Relevant existing regressions and import/format checks pass; any environmental skip is reported explicitly rather than labeled a passed acceptance case.

## Test Specification

Use deterministic fixtures and assert externally observable behavior, including failure atomicity. The following named cases are required; implement them in the test files above with pytest/pytest-asyncio. For the investigation/benchmark deliverable, verify the equivalent measurements and assertions in its runnable benchmark.

| Required case | Expected result |
|---|---|
| `test_primary_continuity` | One recall restores actionable state after deleting conversational context without replaying work. |
| `test_no_false_evidence` | Error results, alias overwrite and mutable evidence have the correct distinct completion outcomes. |
| `test_legacy_regression` | Existing suites pass and disabled schema/output comparison shows no behavior drift. |

New test modules should use local fixtures unless the shared fixture task is already completed. PostgreSQL/Redis concurrency and restart claims require real isolated test services; unit doubles verify only local protocol behavior. Never contact production services or use production data for these tests.

## Agent Instructions

1. Read the approved spec and this task in the feature worktree.
2. Verify every dependency is done in `sdd/tasks/index/workingmemory-toolkit.json` and its completed task artifact exists.
3. Reverify the imports/signatures and read prerequisite implementations; update stale task-specific contract anchors before coding.
4. Set only this task's index status to `in-progress` with assignment/start timestamps and your session ID.
5. Implement the scoped deliverable, preserving others' changes and respecting shared-file ownership/dependency ordering.
6. Run focused tests and relevant regressions, saving logs under `artifacts/logs/`.
7. Move this task to `sdd/tasks/completed/TASK-3002-tm-delivery-a.md` after acceptance passes.
8. Update only this task's per-spec index entry to `done`, set completed_at/file/verification, and fill the completion note. Never use the historical monolithic index.
9. Commit scoped implementation and task state as required by `$sdd-start`; do not mark the feature complete after Delivery A alone.

## Completion Note

**Completed by**: sdd-worker via delegated agent (Claude Opus 5) — 2026-09-09
**Commit**: `f298a78a5`

### What was built

The Delivery A acceptance gate: `test_delivery_a.py` (7 tests) covering
the four-step primary scenario, and `test_disabled_compatibility.py`
(4 tests) covering byte/schema parity with task memory disabled.

### The assertion that carries it

A side-effect **counter** on a fake tool:
`tool.calls == ["load", "clean", "verify", "report"]`, each exactly once
**across the context loss**. That counts real executions rather than
inspecting a status field, which is the only way to actually demonstrate
that recovery does not repeat physical work — the property the whole
feature exists for.

Also pinned: exact version refs surviving recall; `validated` versus
`agent_asserted` completion sources; recall never selecting a task;
overwrite allocating `version+1` while the bound version stays valid; and
the disabled tool surface diffed against a real `git archive dev` tree
imported in a subprocess.

### Verification evidence

- 11 passed, `ruff` clean. Full `tests/tools/working_memory`: 836 passed
  / 78 skipped / 0 failed.
- 8 mutations, all caught.
- **Independently re-verified here**: the dev-tree diff test genuinely
  RUNS rather than skipping (confirmed `PASSED`, not `SKIPPED`), and an
  injected AC10 violation — making recall implicitly select the task —
  is caught by `test_primary_continuity`. The mutated file was confirmed
  clean afterwards.
- Log: `artifacts/logs/task-3002-tm-delivery-a.log`.

### AC coverage, stated plainly

- **Fully covered**: AC1, AC3 (evidence side), AC5, AC7, AC10, AC11, AC13.
- **Partial**: AC4 (per-step provenance yes; concurrent declared-step
  ambiguity and post-dispatch correlation live in TASK-2991's suite);
  AC6 (flags yes, byte-ceiling and pagination no); AC14 (context-leak is
  covered by TASK-2990's suite).
- **Not covered**: AC8, AC9, AC12 — Delivery B durability, deliberately
  out of scope for this task.

### Two behaviours confirmed as correct design, not bugs

1. `status="pending"` maps to `step_reopened` and blocks every transitive
   dependent with `upstream_reopened`, including already-completed ones.
   The non-destructive recovery for a blocked step is `status="running"`.
2. Invalidated evidence is guarded in three independent places; disabling
   any one still refuses the completion, with a different typed error.
   Honest caveat recorded by the agent: mutating only ONE guard is not
   caught, because the assertion accepts either typed refusal — that is
   tolerance of mechanism, not of outcome, and with all three disabled
   the test does fail.

### Delivery A is non-durable

`test_primary_continuity_is_in_process_only_not_durable` shows a fresh
store loses the task, so no test here can be misread as a durability
claim. This task does NOT complete the feature; Delivery B must land too.

### Approved deviations

None.
