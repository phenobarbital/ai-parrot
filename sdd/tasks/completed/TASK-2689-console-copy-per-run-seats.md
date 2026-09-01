# TASK-2689: Console and README stop telling operators to restart

**Feature**: FEAT-490 — Per-run dev-flow model plan
**Spec**: `sdd/specs/per-run-model-plan.spec.md` (Module 5)
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-2688
**Assigned-to**: unassigned

---

## Context

The console banner and the README both say the per-seat plan is fixed at flow
build and that the operator must restart with `DEV_FLOW_*` env keys. After
TASK 4 that is false for a console run. Copy that lies is worse than no copy —
it was the original complaint.

Spec §3 Module 5.

---

## Scope

- Update `planMismatchWarning()` (`dev.html:1770`) and its banner text: no
  restart advice for seats that are now per-run. Keep a message for the one
  case that remains (a resumed run kept its original seats).
- Update `examples/dev_loop/README.md`: the "two limitations" note and the
  `model_plan` section now describe per-run seats, with resume as the caveat.

**NOT in scope**: behaviour (TASK 4), the ops console's docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/dev_loop/static/dev.html` | MODIFY | Banner copy |
| `examples/dev_loop/README.md` | MODIFY | Limitations + model-plan section |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```javascript
// examples/dev_loop/static/dev.html
function planMismatchWarning(response) { ... }   // line 1770
// reads response.model_plan_ignored; returns "" when empty
function showPlanWarning(message) { ... }        // renders into #exec-section
```

### Does NOT Exist
- ~~a second client-side diff~~ — the banner consumes the server's
  `model_plan_ignored` and must not re-derive one. That duplication was
  removed on purpose; do not reintroduce it.

---

## Acceptance Criteria

- [ ] Neither `dev.html` nor `README.md` tells the operator to restart for a
      per-run seat.
- [ ] The resume caveat is stated once, accurately.
- [ ] The existing `TestUiSurfacesTheOverride` copy assertions still pass
      (update them to the new copy where needed).

---

## Test Specification

```python
def test_ui_banner_no_longer_tells_operators_to_restart():
    source = (REPO_ROOT / "examples/dev_loop/static/dev.html").read_text()
    ...
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
**Notes**: Updated `planMismatchWarning()` (`dev.html`) — no longer says
"the per-seat plan is fixed when the server builds its flow, so restart the
console with the DEV_FLOW_* env keys to change these seats"; now says "This
run resumed a checkpoint, and a resumed run keeps the seats it was created
with. Start a fresh run (no run_id) to use these seats.", matching
TASK-2688's corrected backend warning wording exactly (same "resumed a
checkpoint" phrase, consumed by the new `test_ui_banner_no_longer_tells_
operators_to_restart` test). Updated its preceding doc comment block from
"FEAT-486 code-review fix... BUILD-time input" to "FEAT-490... PER-RUN
input", stating the resume caveat explicitly. Rewrote README.md's "Two
limitations" callout (now "Two things worth knowing") — limitation #1
("`model_plan` is a build-time input... Restart the console with the
desired DEV_FLOW_* keys") replaced with the per-run behaviour and the
resume caveat; limitation #2 (judge-panel/review-pair precedence)
untouched, per scope. Added two tests to `test_server_dev_model_plan.py`'s
`TestUiSurfacesTheOverride`: `test_ui_banner_no_longer_tells_operators_to_restart`
(TASK-2689's own named test) and `test_readme_no_longer_tells_operators_to_restart`
(same check on the README section, not in the task's minimal test spec but
directly required by its own acceptance criterion "Neither dev.html nor
README.md tells the operator to restart the console"). All existing
`TestUiSurfacesTheOverride` copy-structure assertions (helper-exists,
driven-by-response, doesn't-use-collapsed-error-box) pass unchanged — none
of them pinned the OLD literal wording, so no update was needed there.
`pytest packages/ai-parrot/tests/flows/dev_flow -q`: 449 passed. `ruff
check` clean.

**Deviations from spec**: none — implemented exactly the two files listed,
consistent with the corrected TASK-2688 wording it depends on.
