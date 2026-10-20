# TASK-4532: Engine task-tier gate in `_consolidate` and same-seat repair in `_run_task`

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-4530, TASK-4531
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (engine half), codex S2 (gate after the last engine mutation, before the merge lock,
against the fork SHA) and S8 (explicit retry state machine). Brainstorm Q2: the repair is a fresh conversation
on the same seat, seeded from the failed branch, with the verdict in the brief; it counts as an attempt.

---

## Scope

- `run_validation(..., tier: Literal["task","merge","feature"], *, attempt_uid=None, base_ref=None)`; `toolkit.coder_run_validation` gains the `task` literal + `attempt_uid`.
- `_task_tier_gate(...)`: start task-tier validation with `base_ref=diff_base`, `wait_verdict` bounded by `roster.runners.gate_overall_timeout_s`.
- `_consolidate`: after `check_banned_imports` passes and before `async with self._acquire_merge_lock`, run the gate; red ⇒ `TaskResult(outcome="validation_failed", validation=…)`; nothing merged.
- `_run_attempt(..., repair_from=None, verdict=None)`: `manager.create(worker_id, base=repair_from)`; verdict rendered (`render_for_prompt`) into `TaskScopedBrief.validation_verdict`.
- `_run_task`: on `validation_failed` and `same_seat_repair` and not yet repaired ⇒ emit the red attempt's outcome, run attempt+1 on the SAME seat with `repair_from=branch`; a second red joins the existing ladder as `err`; never `_classify_and_suspend` for validation reds.
- `prepare_native` (native seats): when a prior native attempt for the task ended `validation_failed`, the new `NativePrep.validation_verdict` carries the rendered verdict.

**NOT in scope**: Dispatcher capability (TASK-4533/4534); docs (TASK-4536).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | gate + repair + run_validation tier |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` | MODIFY | coder_run_validation task tier |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_validation_gate.py` | CREATE | gate + repair tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py` | MODIFY | task-tier admission via toolkit |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.models import TaskResult, ValidationVerdictModel, RunnerConfig  # TASK-4531
from parrot.flows.dev_loop.test_scope.verdict import render_for_prompt  # TASK-4529
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
async def _consolidate_diff_base(feature_branch, branch, *, cwd) -> str          # line 167 (module)
class _FeatureCtx: worktree, feature_id, feature, feature_branch, index_path, spec_path, base_branch   # line 225
async def run_validation(self, feature, worktree, execution_id, task_ids, tier: Literal["merge","feature"], timeout_seconds, request_id) -> BackgroundRegistration   # line 1149
async def prepare_native(...)                                                   # line 2046
async def _consolidate(self, ctx, manager, task, *, branch, path, lock_timeout_s=None) -> TaskResult   # line 2640
#   ~2690: diff_base = await _consolidate_diff_base(ctx.feature_branch, branch, cwd=ctx.worktree)
#   ~2731: violations = await check_banned_imports(path, changed)
#   ~2740: async with self._acquire_merge_lock(lock_timeout_s):
async def _run_attempt(self, ctx, task, seat, *, attempt, job_id, execution_id=None, pool=None) -> Tuple[...]   # line 3090
#   ~3228: await manager.create(self._worker_id(task.task_id, attempt, execution_id))
#   ~3242: coder_feedback=feedback_context,   (inside TaskScopedBrief(...))
async def _select_retry_seat(...)                                               # line 3598
async def _run_task(self, ctx, task, seat, *, job_id, execution_id=None, pool=None) -> TaskResult   # line 3642
#   ~3689 (12-space indent, inside `if not err:`): result = await self._consolidate(ctx, manager, task, branch=branch, path=path)
#   ~3822 (8-space indent, after the ladder):    result = await self._consolidate(ctx, manager, task, branch=branch, path=path)
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py
async def coder_run_validation(self, feature, worktree, execution_id, task_ids, tier: Literal["merge","feature"], timeout_seconds, request_id) -> CoderResult   # line 602; Literal at :608
```

### Does NOT Exist
- ~~`_task_tier_gate`~~ — added here
- ~~`_run_attempt(repair_from=…, verdict=…)`~~ — added here
- ~~a fourth attempt~~ — `AttemptRecord.attempt` is `le=3`

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
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_validation_gate.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._consolidate",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_task",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_attempt",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.run_validation",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.prepare_native",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py#SddCoderToolkit.coder_run_validation"
  ]
}
```

---

## Implementation Notes

- `_consolidate` has two `_consolidate(...)` callers in `_run_task`; the repair hook belongs after the FIRST (12-space indent, inside `if not err:`). The second (after the ladder) must ALSO treat `validation_failed` as terminal-for-this-attempt without another repair.
- Gate disabled (validation supervisor is None) ⇒ log a warning and continue to merge (today's behaviour) — do not fail closed when the engine has no supervisor configured.
- Engine edits are large: keep helpers private and small (<80 lines each).

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. `run_validation` + toolkit literal — *why*: gate reuses the admitted path.
2. `_task_tier_gate` + `_consolidate` hook — *why*: S2.
3. `_run_attempt` repair kwargs — *why*: S8.
4. `_run_task` state machine — *why*: S8.
5. native verdict carry — *why*: parity.
6. Tests with fake supervisor/dispatcher.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        async with self._acquire_merge_lock(lock_timeout_s):' …/engine.py)
# INSERT immediately ABOVE that line (after the banned-import early return, engine.py:~2731-2739):
        verdict = await self._task_tier_gate(
            ctx, task, path=path, branch=branch, diff_base=diff_base,
            attempt_uid=self._attempt_uid_for(task.task_id, branch), execution_id=self._execution_for(branch),
        )
        if verdict is not None and verdict.status != "passed":
            return TaskResult(
                task_id=task.task_id, outcome="validation_failed", branch=branch, worktree_path=path,
                lint=lint_report, validation=ValidationVerdictModel.from_kernel(verdict),
                diagnostics=f"task-tier validation {verdict.status}: {len(verdict.failures)} failure(s)",
            )
# FILL IN: _attempt_uid_for / _execution_for — resolve from self._latest_attempt / registered handles;
#          if a lookup is impossible, generate a uuid4 hex (the gate still needs a unique handle)

    async def _task_tier_gate(self, ctx: _FeatureCtx, task: PlannedTask, *, path: str, branch: str,
                              diff_base: str, attempt_uid: str, execution_id: Optional[str]) -> Optional["ValidationVerdict"]:
        """Run the task tier on the attempt tree after all engine mutations, before the merge lock (S2).

        Returns None when no validation supervisor is configured (logged; merge proceeds as before).
        """
        # FILL IN: self._validation_supervisor.start(tier="task", task_ids=[task.task_id], base_ref=diff_base,
        #          attempt_uid=attempt_uid, worktree=Path(path), request_id=f"gate-{attempt_uid}", …)
        #          then wait_verdict(..., timeout_s=self.roster.runners.gate_overall_timeout_s)
```
**Why**: Placement is the whole point of S2: lint autofix and the banned-import gate are the last engine mutations/checks.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        tier: Literal["merge", "feature"],' …/toolkit.py)
        tier: Literal["task", "merge", "feature"],
# and add a trailing parameter `attempt_uid: Optional[str] = None`, passed through to engine.run_validation(..., attempt_uid=attempt_uid)
# FILL IN: docstring — tier='task' needs one task id, the attempt worktree and attempt_uid
```
**Why**: Same admission rules as the supervisor; the engine supplies base_ref.

### FILL IN checklist
- [ ] `_task_tier_gate` body
- [ ] uid/execution lookup helpers
- [ ] `_run_attempt` repair kwargs
- [ ] `_run_task` state machine (first and post-ladder consolidate)
- [ ] `prepare_native` verdict carry
- [ ] `run_validation` task tier (index check, worktree = attempt path)
- [ ] tests

---

## Acceptance Criteria

- [ ] Gate runs after lint autofix and banned-import check, before the merge lock (spy order test).
- [ ] Red gate ⇒ `validation_failed`, feature branch HEAD unchanged.
- [ ] Repair attempt runs on the same seat, from the failed branch, with the verdict in `TaskScopedBrief.validation_verdict`; attempts list has one record per attempt with one outcome each.
- [ ] Second red ⇒ `_select_retry_seat` is consulted; `_classify_and_suspend` is never called for validation reds.
- [ ] No supervisor configured ⇒ merge proceeds, warning logged.
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_validation_gate.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_toolkit.py -q`

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
7. Close with `scripts/sdd/close_task.sh TASK-4532 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
