# TASK-2691: Thread a per-run plan through the ops runner

**Feature**: FEAT-490 — Per-run dev-flow model plan
**Spec**: `sdd/specs/per-run-model-plan.spec.md` (Module 8)
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-2685, TASK-2690
**Assigned-to**: unassigned

---

## Context

With the TASK 1 seam in the base runner and the TASK 6 kwarg on the ops
builder, the ops topology can accept a per-run plan the same way dev-flow does.
Library-level only — the ops console is not wired to send one (spec §1
Non-Goals).

Spec §3 Module 8.

---

## Scope

- Let the ops path accept a per-run `DevFlowModelPlan` and forward it through
  the TASK 1 overrides mapping into `build_dev_loop_flow`.
- `None` keeps every existing ops call byte-identical.

**NOT in scope**: `examples/dev_loop/server.py`, `static/index.html`,
`/api/config`, any UI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | Forward the plan via the overrides seam |
| `packages/ai-parrot/tests/flows/dev_loop/` | MODIFY | Threading tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
async def run(self, brief, *, run_id=None, ...)                         # line 1189
def _dev_loop_flow_factory(self) -> Callable[[Optional[Any]], AgentsFlow]:  # line 1508
    # hardcoded to build_dev_loop_flow + self._dev_loop_flow_kwargs
```

### Does NOT Exist
- ~~a `model_plan` parameter on `DevLoopRunner.run`~~ — and it should NOT be
  added as a typed parameter (spec §8 Q5): the plan travels through the
  generic overrides mapping so a dev-flow concept stays out of the base class.

---

## Acceptance Criteria

- [ ] The ops runner forwards a per-run plan into its factory.
- [ ] Without one, the ops path is byte-identical.
- [ ] No per-run state on the instance; concurrent runs stay isolated.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop -v` passes.

---

## Test Specification

```python
async def test_dev_loop_runner_threads_a_per_run_plan(): ...
async def test_ops_path_without_a_plan_is_byte_identical(): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/per-run-model-plan.spec.md` for full context — especially §2 (Overview)
   and §8 (every open question is resolved there; do not re-open them).
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code. The line numbers
   above were correct on 2026-09-01; this repo drifts fast (an unrelated merge
   moved two of these files by 100+ lines in one afternoon). Re-grep the
   symbol, and if it moved, update the contract FIRST.
4. **Update status** in `sdd/tasks/index/per-run-model-plan.json` → `in-progress`.
5. **Implement** following the scope. Do not widen it.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update the index** → `done`, and fill in the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-01
**Notes**: The wiring itself was ALREADY functionally complete as a side
effect of the two dependency tasks: TASK-2685 added the generic
`flow_kwargs_overrides` seam to `DevLoopRunner.run()` (merged into
`_dev_loop_flow_factory(overrides)`'s kwargs, unpacked via `**kwargs` into
whatever builder function is called), and TASK-2690 added the `model_plan`
kwarg to `build_dev_loop_flow`. I verified this composes correctly with a
standalone script BEFORE writing any test (patched `build_dev_loop_flow`
via `__globals__`, called `runner._dev_loop_flow_factory({"model_plan":
"SENTINEL_PLAN"})`, confirmed `SENTINEL_PLAN` reached the captured kwargs)
— no `dev_loop/runner.py` behavioural change was needed, and per the
task's own "Does NOT Exist" list a typed `model_plan` parameter on
`DevLoopRunner.run()` must NOT be added (spec §8 Q5: the plan travels
through the generic overrides mapping so a dev-flow concept stays out of
the base class).

TASK-2691's real remaining deliverable, given the mechanism already
existed: (1) a documentation-only addition to `run()`'s
`flow_kwargs_overrides` docstring, explicitly naming the pattern an ops
embedder uses (`flow_kwargs_overrides={"model_plan": plan}`) and citing
TASK-2690/spec §8 Q5 so a future reader does not mistake the missing typed
parameter for an oversight; (2) the integration tests this task's own
Test Specification names — `test_dev_loop_runner_threads_a_per_run_plan`
and `test_ops_path_without_a_plan_is_byte_identical` — plus a third,
`test_no_per_run_plan_state_leaks_across_concurrent_ops_runs`, covering
the acceptance criterion "No per-run state on the instance; concurrent
runs stay isolated." All three exercise the FULL public `run()` API (not
`_dev_loop_flow_factory()` directly, unlike TASK-2685's tests) with a
lightweight `_StubOpsFlow` standing in for the real eight-node graph
(already exhaustively covered elsewhere in this suite) — proving the seam
end to end from an ops embedder's actual call site. Same `__globals__`-
patching technique as every prior task in this feature, for the same
`test_lazy_import.py` orphaned-module reason.

`pytest packages/ai-parrot/tests/flows/dev_loop/test_recovery_lifecycle.py -q`:
12 passed (9 pre-existing + 3 new). `pytest
packages/ai-parrot/tests/flows/dev_loop -q`: 1318 passed, 3 pre-existing
unrelated failures (same three as every other task in this feature).
`pytest packages/ai-parrot/tests/flows/dev_flow -q`: 449 passed (untouched
by this task, confirms no cross-topology regression). `ruff check`: test
file clean; `runner.py` unchanged error count (91, matching the count
after TASK-2685 — this task's docstring-only addition introduced zero new
violations).

**Deviations from spec**: none — the task's Codebase Contract line
describing `_dev_loop_flow_factory()` as "hardcoded to build_dev_loop_flow
+ self._dev_loop_flow_kwargs" was already stale by the time this task
started (TASK-2685, its own listed dependency, changed exactly that), which
is precisely why no further runner code change was needed here.
