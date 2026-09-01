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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
