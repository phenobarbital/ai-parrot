# TASK-4538: Task-tier end-to-end test and budget evidence

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4534, TASK-4537
**Assigned-to**: unassigned
**Discovered-from**: `issue:3edabb9b953e`

---

## Context

Spec §4 integration test `test_task_tier_end_to_end_pytest` and the last §5 criterion: the task-tier gate on a
FEAT-699 replay stays under the pytest budget, with evidence in `artifacts/logs/` (git-ignored ⇒ `git add -f`).

> **Amended 2026-10-20** (`issue:3edabb9b953e`). An earlier pass at this evidence timed the FEAT-699 task
> validation commands *directly* (TASK-4445 3.7 s, TASK-4447 4.2 s, TASK-4451 not measured). That does not
> satisfy the criterion: the budget is a property of the **gate**, which adds planning, spawn, report parse
> and verdict build on top of the bare pytest run. The measurement must replay the gate itself, cover all
> three tasks, and actually exercise the `.parrot/test_runners.toml` pytest `timeout_s`.

---

## Scope

- Create `test_task_tier_end_to_end.py`: hermetic feature worktree + attempt branch with one failing pytest node ⇒ gate red ⇒ same-seat repair (fake dispatcher writes the fix) ⇒ green ⇒ merged; assert two attempt records, one outcome each, verdict in the repair brief.
- Measure the task-tier gate wall clock on three FEAT-699 tasks (TASK-4445, 4447, 4451) replayed against their
  merge commits; write `artifacts/logs/feat-709-task-tier-budget.md` (table: task, runner, tests, seconds,
  under budget?). The measurement MUST drive the real gate path (`_task_tier_gate` → supervisor `tier="task"` →
  `wait_verdict`) against each task's merge commit, not a bare `pytest` invocation, and MUST record the
  gate overhead separately from the test wall clock. All three tasks are measured — none may be left blank.
- Validate the `.parrot/test_runners.toml` pytest `timeout_s` (60 s) against the measured numbers rather than
  leaving it a placeholder: state in the evidence file whether the observed worst case leaves headroom, and
  name the value the measurements support.
- If any measurement exceeds the TOML budget, record it and propose the new value in the Completion Note — do NOT change the TOML here (open question §8 Q4 is the user's).

**NOT in scope**: Changing budgets.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_task_tier_end_to_end.py` | CREATE | integration test |
| `artifacts/logs/feat-709-task-tier-budget.md` | CREATE | evidence (git add -f) |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
# reuse the hermetic-root fixture and fake dispatcher patterns from
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py and test_engine_dispatch.py
```

### Existing Signatures to Use
```python
# FEAT-699 tasks for replay: sdd/tasks/completed/TASK-4445-*.md, TASK-4447-*.md, TASK-4451-*.md (Validation Commands sections)
```

### Does NOT Exist
- ~~a real LLM in the test~~ — fake dispatcher only

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_task_tier_end_to_end.py",
      "action": "CREATE"
    },
    {
      "path": "artifacts/logs/feat-709-task-tier-budget.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- `artifacts/` is git-ignored: `git add -f artifacts/logs/feat-709-task-tier-budget.md` (file only, never the dir).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Integration test — *why*: the whole path.
2. Replay + evidence — *why*: §5 budget AC.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_task_tier_end_to_end.py` (CREATE)
```python
"""FEAT-709: task-tier gate → same-seat repair → merge, end to end (fake seat, real git, real pytest)."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_task_tier_end_to_end_pytest(tmp_path):
    """Red gate on attempt 1, repaired by the same seat on attempt 2, merged once green."""
    # FILL IN: build hermetic repo + feature worktree + per-spec index (copy conftest helpers);
    #          fake dispatcher: attempt 1 commits a failing test fix, attempt 2 commits the correct one
    #          and asserts its brief.validation_verdict starts with "## Validation verdict";
    #          assert result.outcome == "merged", [a.attempt for a in result.attempts] == [1, 2],
    #          both attempts on the same seat_label
```
**Why**: Single test, real subprocess pytest inside a tmp repo.

### FILL IN checklist
- [ ] test body
- [ ] replay measurement + evidence table

---

## Acceptance Criteria

- [ ] Integration test passes.
- [ ] Evidence file exists and is committed with `git add -f`.
- [ ] The evidence is a **gate replay**: it records, per task, the gate wall clock (not just the bare pytest
      time) obtained through `_task_tier_gate`/supervisor `tier="task"`, with gate overhead broken out.
- [ ] All three FEAT-699 tasks (TASK-4445, TASK-4447, TASK-4451) have a measured number; none is "not measured".
- [ ] The pytest `timeout_s` in `.parrot/test_runners.toml` is assessed against the measurements, with the
      supported value named in the evidence file and the Completion Note.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_task_tier_end_to_end.py -q`

---

## Test Specification

Tests live in the files declared above; write the cases named in Acceptance Criteria. sdd_coder tests reuse the hermetic-root fixture in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug language-agnostic-validation-runners --feature-id FEAT-709`), never on `dev`.
2. Every `Depends-on` task must be `done` in `sdd/tasks/index/language-agnostic-validation-runners.json`.
3. Verify the Codebase Contract first; fix stale entries in this file before coding.
4. Implement from the blueprint; complete every `FILL IN`; never change a fixed signature or path.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Stage only the files listed above (`git add -f` for `.claude/`, `.parrot/`, `artifacts/`).
7. Close with `scripts/sdd/close_task.sh TASK-4538 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
