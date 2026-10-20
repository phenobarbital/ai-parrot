# TASK-4541: Gate state hygiene, request identity, and a real budget replay

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4540
**Assigned-to**: unassigned
**Discovered-from**: `issue:3edabb9b953e`

---

## Context

Four findings raised against the delivered gate, grouped because they all concern the gate's bookkeeping
and the evidence that it fits its budget.

1. **Unbounded state.** `_branch_attempts` and `_validation_reds` are only ever written and read; nothing
   prunes them when a task settles, so both grow for the whole life of an engine.
2. **Stale verdict on re-run.** The gate's `request_id` is `f"gate-{attempt_uid}"` with no HEAD SHA, so a
   second gate run for the same attempt after new commits can be served the first run's verdict.
3. **Wait outlives nothing.** `wait_verdict` is called with `timeout_s = gate_overall_timeout_s` — the
   *same* value as the supervisor's own deadline — so the wait can expire at the instant its children do
   rather than strictly after them.
4. **The budget evidence is not a gate replay.** `artifacts/logs/feat-709-task-tier-budget.md` times the
   FEAT-699 tasks' pytest commands directly (TASK-4445 3.69 s, TASK-4447 4.21 s, TASK-4451 "not
   measured"), which does not answer the spec's §5 criterion: the budget is a property of the **gate**,
   which adds planning, spawn, report parse and verdict build on top of the bare pytest run. The pytest
   `timeout_s = 60` in `.parrot/test_runners.toml` is still an unvalidated placeholder.
   TASK-4451's validation commands *are* recoverable (its task file lists three, at lines 224-226); the
   existing note claiming otherwise is wrong.

---

## Scope

- Prune `_branch_attempts` and `_validation_reds` when a task settles, so neither retains entries for
  finished tasks. Pruning must not break the same-seat repair, which reads `_validation_reds` between the
  red attempt and its repair, nor `_attempt_uid_for` / `_execution_for`, which read `_branch_attempts`
  during `_consolidate`.
- Gate `request_id` includes the attempt's HEAD SHA, so a re-run after new commits cannot be served a
  stale verdict.
- `wait_verdict` is given a timeout strictly below `gate_overall_timeout_s`, so the wait cannot expire
  before the children it waits on.
- Regenerate `artifacts/logs/feat-709-task-tier-budget.md` as a **gate replay**: drive the real gate path
  for TASK-4445, TASK-4447 and TASK-4451, each against its own merge commit as `base_ref`, recording per
  task the gate wall clock, the bare pytest wall clock, and the difference as gate overhead. All three are
  measured; none may be left blank.
- Assess pytest `timeout_s = 60` against the measured worst case and name the value the measurements
  support. Do **not** change the TOML here — §8 Q4 is the user's call; propose in the Completion Note.

**NOT in scope**: changing budgets in `.parrot/test_runners.toml`; the fail-closed gate (TASK-4540);
the max_turns arm (TASK-4539).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | pruning, request_id SHA, wait timeout |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_validation_gate.py` | MODIFY | hygiene regressions |
| `artifacts/logs/feat-709-task-tier-budget.md` | MODIFY | gate-replay evidence (git add -f) |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `feat-FEAT-709-language-agnostic-validation-runners` @ `616450ad0` (2026-10-20).

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
async def _git(*args: str, cwd: str) -> Tuple[int, str, str]                      # line 163 (module-level)
async def _consolidate_diff_base(feature_branch, branch, *, cwd) -> str           # line 175
self._branch_attempts: Dict[str, Tuple[str, str, str, int]] = {}                  # line 474
self._validation_reds: Dict[Tuple[str, str], Tuple[str, int, str]] = {}           # line 477
def _attempt_uid_for(self, task_id: str, branch: str) -> str                      # line 1336
def _execution_for(self, branch: str) -> Optional[str]                            # line 1346
def _record_validation_red(self, task_id: str, branch: str, rendered: str) -> None  # line 2865
#   :1424  timeout_s = self.roster.runners.gate_overall_timeout_s
#   :1432  request_id=f"gate-{attempt_uid}",
#   :1437  return await self._validation_supervisor.wait_verdict(execution_id, registration.handle, timeout_s)
#   :2318  self._validation_reds.pop((execution_id or "", task_id), None)      <- existing pop site
#   :3944  rendered = self._validation_reds.pop(red_key, ...)[2]               <- repair consumes the red
#   :3962  self._validation_reds.pop(red_key, None)
```

### Does NOT Exist
- ~~a prune/cleanup helper for `_branch_attempts`~~ — added here
- ~~a HEAD SHA in the gate `request_id`~~ — added here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_validation_gate.py",
      "action": "MODIFY"
    },
    {
      "path": "artifacts/logs/feat-709-task-tier-budget.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._task_tier_gate",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_task"
  ]
}
```

---

## Implementation Notes

- **Prune at the end of `_run_task`**, where the task's final `TaskResult` is known — not in `_consolidate`,
  which runs once per attempt and whose state the repair path still needs.
- The repair path pops `_validation_reds` itself (`:3944`, `:3962`); the prune is a belt-and-braces sweep for
  the keys a settled task leaves behind, so it must be written as "discard if present", never as an assert.
- `_branch_attempts` is keyed by branch; a task owns several branches across attempts. Collect the task's
  branches as you prune rather than scanning the whole dict by value.
- For the `request_id` SHA, rev-parse `HEAD` in the attempt worktree (`path`) with the module-level `_git`;
  on a non-zero rc fall back to today's `f"gate-{attempt_uid}"` rather than failing the gate.
- Give `wait_verdict` a timeout strictly below the supervisor deadline — a small fixed margin is enough;
  name the margin as a module constant rather than scattering a literal.

---

## Implementation Blueprint

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# 1. request_id with the attempt HEAD SHA, inside _task_tier_gate before `start(...)`:
        rc, head_sha, _err = await _git("rev-parse", "HEAD", cwd=path)
        request_id = f"gate-{attempt_uid}-{head_sha.strip()[:12]}" if rc == 0 and head_sha.strip() else f"gate-{attempt_uid}"

# 2. wait strictly inside the supervisor deadline:
        return await self._validation_supervisor.wait_verdict(
            execution_id, registration.handle, max(1, timeout_s - _GATE_WAIT_MARGIN_S)
        )
# with, near the module constants:
_GATE_WAIT_MARGIN_S = 5   # the gate's own wait expires before the supervisor deadline, never with it

# 3. prune helper + call at the end of _run_task, once the TaskResult is final:
    def _forget_task_state(self, task_id: str, execution_id: Optional[str]) -> None:
        """Drop the per-attempt bookkeeping a settled task leaves behind (issue:3edabb9b953e)."""
        # FILL IN: pop self._validation_reds[(execution_id or "", task_id)] if present;
        #          pop every self._branch_attempts entry whose branch belongs to this task.
```
**Why**: three independent leaks/races in the same bookkeeping, fixed where the task settles.

### `artifacts/logs/feat-709-task-tier-budget.md` (MODIFY)
```markdown
# FILL IN: regenerate as a gate replay. Required columns per task:
#   Task | merge commit | runner | tests | gate wall clock (s) | bare pytest (s) | gate overhead (s) | under 60 s
# Required prose: how the replay was driven (supervisor tier="task", base_ref=<merge commit>),
#   the observed worst case, and the pytest timeout_s the measurements support.
# TASK-4451's commands come from its task file (test_background_contract.py,
#   test_background_validation.py, test_supervisor_ledger.py) -- it IS measurable.
```

### FILL IN checklist
- [ ] `request_id` HEAD SHA + fallback
- [ ] `wait_verdict` margin + constant
- [ ] `_forget_task_state` + its call site in `_run_task`
- [ ] hygiene tests
- [ ] regenerated gate-replay evidence

---

## Acceptance Criteria

- [ ] After a task settles (merged, validation_failed, or failed), `_branch_attempts` and
      `_validation_reds` hold no entry for it; the same-seat repair still works end to end.
- [ ] The gate `request_id` differs between two gate runs for the same `attempt_uid` at different HEAD
      SHAs, and falls back to `gate-{attempt_uid}` when `rev-parse` fails.
- [ ] `wait_verdict` is called with a timeout strictly less than `gate_overall_timeout_s`.
- [ ] `artifacts/logs/feat-709-task-tier-budget.md` records, for **all three** of TASK-4445, TASK-4447 and
      TASK-4451, a gate wall clock obtained through the real gate path against that task's merge commit,
      with bare pytest time and gate overhead broken out. No row says "not measured".
- [ ] The evidence names the pytest `timeout_s` the measurements support and states the observed worst case.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_validation_gate.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py -q`

---

## Test Specification

Tests live in the files declared above; write the cases named in Acceptance Criteria. The evidence file is
git-ignored — commit it with `git add -f`.

---

## Agent Instructions

1. Work in the feature worktree, never on `dev`.
2. Verify the Codebase Contract first.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
4. Stage only the files listed above (`git add -f` for `artifacts/`).
5. Close with `scripts/sdd/close_task.sh TASK-4541 language-agnostic-validation-runners verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
