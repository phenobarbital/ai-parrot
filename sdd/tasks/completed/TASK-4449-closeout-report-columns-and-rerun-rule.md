# TASK-4449: Closeout table — new red / baseline red / cached / unknown, and the re-run rule

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4446
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (rendering half), §5 AC "/sdd-done table shows new red / baseline red / cached / unknown".
The FEAT-698 closeout table summed 15 merge runs into "11,096 tests, 100 failed" — and then skipped the
final run because of `RERUN_TASK_THRESHOLD` (report.py:30). With contract-driven plans the feature tier is
cheap, so the spec's §8 default applies: **drop the `> 10 tasks ⇒ skip` rule** (the fresh closeout run is
the point of the feature). If the human decides otherwise before implementation, they edit this task.

---

## Scope

- `report.py`:
  - delete `RERUN_TASK_THRESHOLD`; `should_rerun(task_count)` returns `True` for any `task_count >= 1`
    (0 tasks ⇒ False) — hard cut, no shim (internal API, no external consumers).
  - add `cached` to `TaskTestRecord`: `cached: tuple[str, ...] = ()` (targets skipped by the green cache),
    read with a default in `_record_from_payload`, and an `append_cached(feature_id, task_id, targets)`
    writer using the same lock/atomic pattern as `append_suite`.
  - `render_markdown`: add columns `New red | Baseline red | Unknown` computed from each `SuiteResult.baseline`
    (`new_red`/`baseline_red`/`unknown` counts; `—` when a suite has failures but no baseline data), a
    `Cached` total line (`cached (skipped, unchanged since green): <n> target(s)`), and a verdict line:
    `Gate: ✅ no new reds` / `Gate: ❌ <n> new red, <m> unknown` / `Gate: ⚠️ failures not classified`
    (failures present but no baseline data). The Final-HEAD re-run column is kept.
- `scripts/sdd/test_report.py`: `decide-rerun` prints `rerun` (or `skip (no tasks)` for an empty index);
  `render` drops the threshold-based `rerun_skip_reason` (pass `None` unless the index has 0 tasks).
- Tests: `test_report.py` (kernel) and the existing CLI module `tests/sdd_scripts/test_test_report.py`
  (verified: it is the only test importing `scripts.sdd.test_report`). Any assertion there that encodes the
  `> 10 tasks ⇒ skip` rule is re-baselined (hard cut).

**NOT in scope**: producing `baseline` data (TASK-4450/4451), `/sdd-done` doc wording (TASK-4452).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | MODIFY | Columns, cached, re-run rule |
| `scripts/sdd/test_report.py` | MODIFY | decide-rerun / render |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py` | MODIFY | Render/rule tests |
| `tests/sdd_scripts/test_test_report.py` | MODIFY | CLI tests; re-baseline threshold assertions |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# report.py
RERUN_TASK_THRESHOLD = 10                                   # line 30 (DELETE)
class TaskTestRecord: feature_id, task_id, head_sha, base_ref, tier, source, recorded_at, attempts, suites, notes  # line 52
def append_suite(feature_id, task_id, result, *, head_sha, base_ref, tier, source, note=None) -> Path | None  # line 186
def should_rerun(task_count: int) -> bool:                  # line 258
def render_markdown(records, task_ids, *, final_head, rerun, rerun_skip_reason) -> str  # line 289
# SuiteResult.baseline: tuple[(nodeid, status)]            # TASK-4446
# scripts/sdd/test_report.py
#   line 88-92: decide-rerun branch uses report_mod.should_rerun / RERUN_TASK_THRESHOLD
#   line 96-100: rerun_skip_reason built from RERUN_TASK_THRESHOLD
```

### Does NOT Exist
- ~~`TaskTestRecord.cached`, `append_cached`~~ — created here
- ~~any remaining reader of `RERUN_TASK_THRESHOLD` after this task~~ — `grep -rn RERUN_TASK_THRESHOLD` must return
  only docs that TASK-4452 rewrites (`.claude/commands/sdd-done.md` and twins)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py", "action": "MODIFY"},
    {"path": "scripts/sdd/test_report.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_test_report.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#render_markdown",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#should_rerun",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#append_suite",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#TaskTestRecord",
    "sym:scripts/sdd/test_report.py#main"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Re-run rule + `TaskTestRecord.cached` + `append_cached` — *why*: §8 default; cached rows need storage.
2. `render_markdown` columns + gate line — *why*: reviewers must see new reds, not raw reds.
3. Script changes, then tests.

### `report.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^RERUN_TASK_THRESHOLD = 10$' report.py) — DELETE that line (report.py:30)
# REPLACE should_rerun (verified: report.py:258-260):
def should_rerun(task_count: int) -> bool:
    """FEAT-699: the closeout feature-tier run is cheap now — always re-run when the feature has tasks."""
    return task_count >= 1
```
```python
# AFTER `notes: tuple[str, ...] = field(default_factory=tuple)` in TaskTestRecord (verified: report.py:64)
    cached: tuple[str, ...] = field(default_factory=tuple)  # FEAT-699: targets skipped by the green cache
```
```python
def append_cached(feature_id: str, task_id: str, targets: Sequence[str], *, head_sha: str, base_ref: str,
                  tier: str, source: str) -> Path | None:
    """Merge cached target paths into a task record (same lock/atomic idiom as append_suite)."""
    # FILL IN — mirror append_suite (report.py:186-232); union + sort the cached tuple
    raise NotImplementedError
# render_markdown (report.py:289): FILL IN — new columns, cached line, gate line; keep deterministic ordering
```

### FILL IN checklist
- [ ] `append_cached`; `_record_from_payload` default for `cached`
- [ ] `render_markdown` columns/lines exactly as Scope words them
- [ ] script: decide-rerun + render
- [ ] tests: gate line variants, `—` cell, cached line, old payload without `cached`, decide-rerun for 15 tasks prints `rerun`

---

## Acceptance Criteria

- [ ] `decide-rerun` on a 15-task index prints `rerun`.
- [ ] A record whose only failures are `baseline_red` renders `Gate: ✅ no new reds`.
- [ ] Failures without baseline data render `Gate: ⚠️ failures not classified` and `—` cells.
- [ ] Old record JSON (no `cached`, no `baseline`) still renders.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py -q`
- `pytest tests/sdd_scripts/test_test_report.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_test_report.py (append)
from scripts.sdd import test_report as cli

def test_decide_rerun_always_for_nonempty_index(tmp_path, capsys):
    # FILL IN: write a 15-task index, run cli.main(["decide-rerun", "--index", str(idx)]), assert "rerun"
    ...
```

---

## Agent Instructions

Standard. Close with `scripts/sdd/close_task.sh TASK-4449 tests-optimization-sdd-flow verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
