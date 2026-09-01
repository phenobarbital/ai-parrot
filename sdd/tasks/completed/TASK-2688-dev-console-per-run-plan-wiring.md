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

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-01
**Notes**: In `handle_run` (`server_dev.py`): (1) narrowed `effective_plan`
to `requested_plan` when `requested_plan is not None and resume_run_id is
None` — i.e. on the fresh path — so the pre-existing `plan_diffs =
_plan_field_diffs(requested_plan, effective_plan)` computation (unchanged
code) naturally returns `[]` for a fresh run (requested == effective) and
still returns the real diff for a resume (effective_plan stays the
server's static default); (2) passed `model_plan=requested_plan`
unconditionally into `runner.run(...)` — safe on both paths since
TASK-2687's runner already no-ops it on a resumed run; (3) updated the
backend warning log text (previously "restart the console with the
DEV_FLOW_* env keys") to state the actual remaining case (a resumed run
keeps its original seats); (4) updated the `model_plan_ignored`/`model_plan`
response-field comments accordingly. Every change is confined to
`examples/dev_loop/server_dev.py`; no other files.

**Deviations from spec — load-bearing, read this**: TASK-2688's Codebase
Contract ("Does NOT Exist": *"a client-supplied `run_id` — no code path
reads one; the mint at `:640` is the only source"*) and its third
recommended test (`test_console_run_id_is_always_fresh`) are **stale**.
Commit `345da8769` ("feat(dev-flow console): resume an interrupted run
from its run_id"), visible in `git log` on `dev` BEFORE this feature
branch was cut, added `_parse_resume_run_id(form)` to `handle_run` —
the console genuinely accepts a caller-supplied `run_id` and resumes a
checkpointed run through the SAME preflight/`inspect_checkpoint` machinery
`test_server_dev.py`'s own resume suite already covers. The spec's §1
"the console can only ever take the fresh path" / "no resume endpoint"
argument was true when written (2026-09-01, revision 0.1/0.2) but the
spec's own revision history (0.3) already flags that an "unrelated merge"
moved `server_dev.py` by ~120 lines that same afternoon — this resume
feature is that merge.

I did NOT stop, because the fix is unambiguous and consistent with work
already merged in THIS feature: TASK-2687 already built exactly the
mechanism this needs (`DevCheckpointCoordinator.prepare()` never calls
`flow_factory` on the resume branch, so a resumed run's seats are
unaffected by construction). I adapted `handle_run` to the two real cases
instead of the one the spec assumed:
  - **Fresh** (no `run_id`, or a `run_id` neither present nor resumable —
    unchanged 409 behaviour): the submitted plan is threaded in and fully
    applied; `model_plan_ignored` is `[]`; the response echoes the
    submission. This is the common case and matches the spec's intent
    exactly.
  - **Resume** (a `run_id` that preflights as resumable): unchanged from
    pre-FEAT-490 behaviour — the newly submitted plan is validated,
    diffed against the server's static default, logged, and reported as
    ignored; it does not reach the run (TASK-2687's rule). The backend
    warning's wording was corrected (see above); this task's scope
    excludes the UI banner (TASK-2689 owns `dev.html`/`README.md`).

Rewrote/added tests in `test_server_dev_model_plan.py` accordingly:
extended `make_client` with the same `checkpoint_store`/
`dev_loop_flow_kwargs` opt-in `test_server_dev.py`'s fixture already uses
(omitted by default — every pre-existing test below stays on the
unaffected code path); `test_response_echoes_the_effective_plan` now
asserts the submission is echoed (was: the server default);
`test_ignored_seat_is_reported_to_the_console` was replaced by
`test_run_endpoint_reports_nothing_ignored_on_fresh_run` (asserts `[]`)
plus new resume-scoped tests (`test_ignored_seat_is_reported_on_resume`,
`test_matching_plan_on_resume_reports_nothing_ignored`,
`test_warning_names_the_differing_seat_on_resume`) built the same way
`test_server_dev.py`'s `test_resumable_run_id_is_used_as_the_run_identity`
simulates a resume (monkeypatched `inspect_checkpoint` + `prepare`
returning `"resumed"`, no real checkpoint store needed since
`model_plan_ignored` is decided synchronously before the background run
starts); added `test_run_endpoint_applies_ideation_model` (spec §4's named
test) and `test_console_mints_a_fresh_run_id_when_none_is_supplied`
(corrected replacement for the stale `test_console_run_id_is_always_fresh`,
documenting precisely what still holds vs. what the resume feature
changed). `pytest packages/ai-parrot/tests/flows/dev_flow -q`: 447 passed
(includes the untouched `test_server_dev.py`'s 65, confirming no
regression to the resume suite itself). `ruff check` clean on both files.

**Recommendation for the feature owner**: the spec's §1 "Non-Goals" / §8
Q4 text should be corrected in a follow-up doc pass to acknowledge the
resume endpoint exists (TASK-2692, docs/dev_loop/dev-flow-model-plan.md,
already covers documenting the resume rule — this note flags that its
"no resume endpoint" framing needs the same correction applied here).
