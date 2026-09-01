# TASK-2686: Accept a per-run model_plan on DevFlowRunner.run

**Feature**: FEAT-490 — Per-run dev-flow model plan
**Spec**: `sdd/specs/per-run-model-plan.spec.md` (Module 1)
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-2685
**Assigned-to**: unassigned

---

## Context

`build_dev_flow(model_plan=…)` bakes each seat into a node constructor, and the
console builds one flow at startup — so a submitted plan is validated, echoed
and then ignored. But since FEAT-480 a run with a stable `run_id` and
`dev_loop_flow_kwargs` already builds a **fresh flow per run**: on a cache miss
`DevCheckpointCoordinator.prepare()` calls `flow_factory(None)`
(`dev_loop/checkpoint.py:555`) → `build_dev_flow(**kwargs)`
(`dev_flow/runner.py:318`). The plan is simply not threaded into those kwargs.

Spec §1 (the finding), §3 Module 1.

---

## Scope

- Add `model_plan: DevFlowModelPlan | None = None` (keyword-only) to
  `DevFlowRunner.run()`.
- Merge it into the flow-build kwargs for that run via the TASK 1 overrides
  seam, so `build_dev_flow` receives it on the fresh path.
- Record the run's effective plan so later tasks can report it (the runner
  already persists a snapshot and a bundle).

**NOT in scope**: the resume rule (TASK 3), the console (TASK 4), the ops
topology (TASKS 6-7), any fingerprint change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/runner.py` | MODIFY | `run()` + `_dev_loop_flow_factory()` |
| `packages/ai-parrot/tests/flows/dev_flow/test_dev_flow_runner*.py` | MODIFY/CREATE | Per-run plan tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
<!-- Re-verified 2026-09-01 against the current tree (an unrelated merge had
     moved server_dev.py and dev_loop/runner.py by 100+ lines). -->
```python
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan, resolve_model_plan  # model_plan.py:167, :334
from parrot.flows.dev_flow.flow import build_dev_flow                              # dev_flow/flow.py:86
from parrot.flows.dev_flow.runner import DevFlowRunner                             # dev_flow/runner.py:40
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_flow/runner.py
class DevFlowRunner(DevLoopRunner):                                     # line 40
    async def run(                                                      # line 79
        self,
        brief: DevRequestBrief | FeatureBrief,
        *,
        run_id: str | None = None,
        initial_task: str = "",
        extra_shared: dict[str, Any] | None = None,
    ) -> FlowResult: ...
    def _dev_loop_flow_factory(self) -> Callable[[Any], AgentsFlow]:    # line 297
        # kwargs = dict(self._dev_loop_flow_kwargs)
        # returns build_dev_flow(**kwargs, checkpoint=True,             # line 318
        #                        checkpoint_required=True, checkpoint_store=...)
    def _execution_policy_for_fingerprint(self) -> dict[str, Any]:      # line 327

# packages/ai-parrot/src/parrot/flows/dev_flow/flow.py
def build_dev_flow(*, dispatcher, redis_url, ...,                       # line 86
                   model_plan: DevFlowModelPlan | None = None)          # line 101
```

### Does NOT Exist
- ~~`DevFlowRunner.set_model_plan()`~~ — the plan is not mutable runner state
  and must not become it.
- ~~`build_dev_flow(model_plan_override=…)`~~ — the kwarg is `model_plan` and
  already exists.
- ~~`AgentsFlow.rebuild_nodes()` / `set_node_model()`~~ — no API re-seats a
  constructed flow. Per-run seats come from building a new flow.

---

## Implementation Notes

### Key Constraints
- Same concurrency rule as TASK 1: per-call closure, never `self`.
- `model_plan=None` ⇒ the `build_dev_flow` call must be byte-identical to
  today's, for every embedder.
- Precedence inside `build_dev_flow` is unchanged: an explicit
  `codereview_dispatcher` still wins over the plan's review pair
  (`dev_flow/factories.py:274`).

---

## Acceptance Criteria

- [ ] `DevFlowRunner.run(model_plan=…)` reaches `build_dev_flow` for that run.
- [ ] `run()` without a plan is byte-identical to today.
- [ ] Two concurrent runs with different plans build with their own seats.
- [ ] No per-run plan is stored on the runner instance.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_flow -v` passes.

---

## Test Specification

```python
async def test_per_run_plan_reaches_build_dev_flow(): ...
async def test_run_without_plan_is_byte_identical(): ...
async def test_concurrent_runs_do_not_leak_seats(): ...
async def test_plan_is_not_stored_on_the_instance(): ...
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
**Notes**: Added `model_plan: DevFlowModelPlan | None = None` (keyword-only)
to `DevFlowRunner.run()`. It is merged into a `flow_kwargs_overrides` dict
(`{"model_plan": model_plan}` when not `None`) built as a local variable and
passed to `self._dev_loop_flow_factory(flow_kwargs_overrides)` — never
stored on `self`. `_dev_loop_flow_factory()` now accepts an optional
`overrides` param (mirrors TASK-2685's base-class seam) and merges it over
`dict(self._dev_loop_flow_kwargs)` per call. Also recorded
`result.metadata["model_plan_requested"]` (the requested plan's
`model_dump(mode="json")`, or `None`) right before `run()` returns, so a
caller can see what was submitted — TASK-2687 refines this for the resumed
case (original seats win; the newly submitted plan must be reported as not
applied). Added 4 tests to `test_runner.py`: byte-identical without a plan,
a plan reaching `build_dev_flow`, no per-run plan left on the instance, and
two back-to-back factory closures with different plans not leaking into
each other — same `__globals__`-patching technique as TASK-2685 (not a
dotted monkeypatch string), for the same `test_lazy_import.py` orphaned-
module reason documented there. `pytest packages/ai-parrot/tests/flows/dev_flow -q`:
438 passed. `pytest packages/ai-parrot/tests/flows/dev_loop -q`: 1296 passed,
3 pre-existing unrelated failures (same ones verified failing on `dev`
before this feature). `ruff check` clean on both modified files.

**Deviations from spec**: none
