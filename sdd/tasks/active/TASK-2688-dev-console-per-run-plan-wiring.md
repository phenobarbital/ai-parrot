# TASK-2688: Dev console passes the parsed plan into the run

**Feature**: FEAT-490 — Per-run dev-flow model plan
**Spec**: `sdd/specs/per-run-model-plan.spec.md` (Module 4)
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-2686, TASK-2687
**Assigned-to**: unassigned

---

## Context

`handle_run` already parses and validates the submitted plan
(`_parse_model_plan`, `server_dev.py:183`), diffs it against the server's
(`_plan_field_diffs`, `:394`) and reports the difference as
`model_plan_ignored` (`:793`). All that is left is to actually pass it to the
run — and then stop reporting anything as ignored, because nothing will be.

The console mints its own `run_id` (`:640`) and has no resume endpoint, so
every console run is a checkpoint cache miss and the plan always applies
(spec §8 Q4).

Spec §3 Module 4.

---

## Scope

- Pass `requested_plan` into `runner.run(...)` (`server_dev.py:736`).
- Narrow `model_plan_ignored`: for a console-started run it is always `[]`.
  Keep the field in the response (the console reads it) rather than removing
  it, so an embedder reusing a `run_id` can still be told.
- Keep echoing the effective plan in the run response.

**NOT in scope**: UI copy (TASK 5), the ops console (out of scope entirely —
spec §1 Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/dev_loop/server_dev.py` | MODIFY | `handle_run` passes the plan; ignored-list narrows |
| `packages/ai-parrot/tests/flows/dev_flow/test_server_dev_model_plan.py` | MODIFY | Endpoint tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# examples/dev_loop/server_dev.py
def _parse_model_plan(form: dict[str, Any]) -> DevFlowModelPlan | None:   # line 183
def _model_plan_payload(plan, *, review_pair_active: bool = True) -> dict # line 353
def _plan_field_diffs(requested, effective, *, prefix="") -> list[str]    # line 394
async def handle_run(request: web.Request) -> web.Response:               # line 576
    run_id = f"run-{uuid.uuid4().hex[:8]}"                                # line 640
    result = await runner.run(                                            # line 736
        brief, run_id=run_id, initial_task=..., extra_shared=...)
    "model_plan_ignored": plan_diffs,                                     # line 793
    "model_plan": _model_plan_payload(...)                                # line 794
dev_loop_flow_kwargs: dict[str, Any] = { ... }                            # line 1002
app["flow"] = build_dev_flow(**dev_loop_flow_kwargs)                      # line 1029
```

### Does NOT Exist
- ~~a client-supplied `run_id`~~ — no code path reads one; the mint at `:640`
  is the only source. The always-fresh premise depends on this staying true.
- ~~a resume endpoint on this console~~.

---

## Implementation Notes

The existing `dev_pool` carve-out in the diff (added when the development pool
became per-run) is the precedent: once a seat is genuinely per-run it stops
being reported as ignored. This task extends that to the remaining seats.

---

## Acceptance Criteria

- [ ] A run with a differing `research_primary` builds with that model.
- [ ] `model_plan_ignored == []` for every console-started run.
- [ ] The run response still echoes the effective plan.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_flow -v` passes.

---

## Test Specification

```python
async def test_run_endpoint_applies_ideation_model(): ...
async def test_run_endpoint_reports_nothing_ignored(): ...
async def test_console_run_id_is_always_fresh():
    """Pins the premise the reporting rests on."""
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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
