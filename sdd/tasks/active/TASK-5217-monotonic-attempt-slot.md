# TASK-5217: Re-dispatched attempts take the next free attempt slot

**Feature**: FEAT-812 — coder_record_review/feedback accept validated models, and re-dispatched attempts never collide
**Spec**: `sdd/specs/ledger-coder-reviews-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:3b913ffd77cd`

---

## Context

Spec §1 B2 / §2 "B2". `_run_attempt` derives branch and sub-worktree path from
`_worker_id(task_id, attempt, execution_id)`, and every `_run_task` restarts `attempt` at 1. Failed
attempts keep their branch and sub-worktree, so a second `coder_run_chunk` for the same task in the
same execution collides (`git worktree add failed`). FEAT-806 hit it with TASK-5210 a1..a3 kept.

---

## Scope

- Add `SddCoderEngine._free_attempt(ctx, task_id, requested, execution_id) -> int`: smallest
  `n >= requested`, greater than every attempt number already used for this task+execution (git
  refs filtered like `_merged_attempt_branch`, plus `self._branch_attempts`), whose branch does not
  exist locally and whose path does not exist on disk; search up to `_MAX_ATTEMPT_NUMBER = 20`;
  return `requested` unchanged if nothing in range is free.
- Call it at the top of `_run_attempt` (before `manager`, `branch`, `path` are derived), rebinding
  `attempt`.
- Raise `attempt` bounds `le=3` → `le=20` in `AttemptRecord` (models.py) and both telemetry rows
  (telemetry.py:52, :90).
- Tests: leftover `…-a1` branch → attempt 2 used; no leftovers → attempt 1 (existing
  `test_engine_attempt_cwd_is_task_branch` already covers that); `AttemptRecord(attempt=4, ...)` validates.

**NOT in scope**: reclaiming kept worktrees; native `prepare_native`; naming scheme / parsers in
`inspection.py`; the toolkit fix (TASK-5216).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | `_free_attempt` helper + call in `_run_attempt` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | `AttemptRecord.attempt` le=20 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py` | MODIFY | two `attempt` fields le=20 |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine  # verified: test_engine_dispatch.py:13
from parrot.flows.dev_loop.sdd_coder.models import AttemptRecord  # verified: sdd_coder/models.py:388
# engine.py already imports asyncio, os, Path and defines module-level `async def _git(*args, cwd)`
```

### Existing Signatures to Use
```python
# engine.py:2194-2200 — def _worker_id(self, task_id, attempt, execution_id) -> str
#   base = f"{task_id}.a{attempt}"; suffixed ".<exec hex>" when execution_id
# engine.py:2202 — def _branch_for(self, ctx: _FeatureCtx, task_id: str, attempt: int, execution_id: Optional[str]) -> str
# engine.py:2206 — def _path_for(self, ctx: _FeatureCtx, task_id: str, attempt: int, execution_id: Optional[str]) -> str
# engine.py:2214 — async def _merged_attempt_branch(self, ctx, task_id, execution_id) -> Optional[str]
#   prefix = f"{ctx.feature_branch}--{task_id}-a"
#   rc, out, _err = await _git("branch", "--list", f"{prefix}*", "--format=%(refname:short)", cwd=ctx.worktree)
#   attempt_part = name[len(prefix):].split("-", 1)[0]; exec_hex = execution_id.replace("-", "")
#   filter: name.endswith(exec_hex) when exec_hex
# engine.py:489 — self._branch_attempts: Dict[str, Tuple[str, str, str, int]]  (branch -> (uid, exec_id, path, attempt))
# engine.py:3501 — async def _run_attempt(self, ctx, task, seat, *, attempt: int, job_id, execution_id=None,
#                    pool=None, repair_from=None, verdict=None) -> Tuple[AttemptRecord, ..., str, str]
#   engine.py:3521 assert seat.backend is not None, "_run_attempt is only called for mcp seats; native tasks use prepare_native"
#   engine.py:3522 manager = self._manager_for(ctx, task.task_id, attempt, execution_id)
# models.py:391 — attempt: int = Field(..., ge=1, le=3)   (AttemptRecord)
# telemetry.py:52 and :90 — attempt: int = Field(..., ge=1, le=3)
# Without execution_id the pool path is f"{base_path}/{feature_branch}--pool/{task_id}-a1"
#   and the branch is f"{feature_branch}--{task_id}-a1" (test_engine_dispatch.py:127)
# test_engine_dispatch.py helpers: _git(*args, cwd) (line 67), _roster(...) (line 92),
#   fixture noop_probe (line 104), fixture git_sandbox_feature -> (worktree, feature_branch, base_path, index_path),
#   fake_builder_factory({}) -> builder where every seat delivers
```

### Does NOT Exist
- ~~`SddCoderEngine._next_attempt`~~ / ~~`_free_attempt`~~ — created by this task.
- ~~`SubWorktreeManager.exists()`~~ — check the path with `os.path.isdir` via `asyncio.to_thread`.
- ~~`_MAX_ATTEMPT_NUMBER`~~ — created by this task (module constant in engine.py).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/telemetry.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_attempt",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._branch_for",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._path_for",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#AttemptRecord"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Raise the three `le=3` bounds to `le=20` — because a fourth attempt for a task must validate.
2. Add `_MAX_ATTEMPT_NUMBER = 20` near `_GATE_WAIT_MARGIN_S` in engine.py.
3. Add `_free_attempt` right before `_merged_attempt_branch` — reuse its ref-listing convention so
   numbering matches the parsers.
4. Call it at the top of `_run_attempt` — before `manager`/`branch`/`path`, so all three agree.
5. Add tests; run Validation Commands.

### `engine.py` (MODIFY)
```python
# AFTER `_GATE_WAIT_MARGIN_S = 5` (occurrences: 1, verified: engine.py:175)
#: Highest sub-worktree attempt number `_free_attempt` will hand out for one task+execution.
_MAX_ATTEMPT_NUMBER = 20

# BEFORE `    async def _merged_attempt_branch(` (occurrences: 1, verified: engine.py:2214)
    async def _free_attempt(
        self, ctx: _FeatureCtx, task_id: str, requested: int, execution_id: Optional[str]
    ) -> int:
        """First attempt number >= *requested* whose branch and sub-worktree are both free.

        Failed attempts keep their branch and sub-worktree, and `_run_task` restarts numbering at 1,
        so a re-dispatch in the same execution would collide on `git worktree add` (issue:3b913ffd77cd).
        Numbers stay monotonic: the result is also above every number this task+execution already used.
        Returns *requested* unchanged when nothing up to `_MAX_ATTEMPT_NUMBER` is free.
        """
        # FILL IN: collect used numbers from `git branch --list <prefix>*` (same prefix/exec-hex filter
        #          as _merged_attempt_branch) and from self._branch_attempts entries for this branch prefix
        # FILL IN: if `requested` is neither used nor taken, return it (AC5); otherwise scan
        #          n = max(requested, max(used) + 1) .. _MAX_ATTEMPT_NUMBER and return the first free n
        # FILL IN: "taken" = branch name in the listed refs/_branch_attempts OR
        #          await asyncio.to_thread(os.path.isdir, self._path_for(...))
        # FILL IN: log at info when the number changes

# INSIDE _run_attempt — insert after the assert (disambiguated, occurrences of manager line: 2)
        assert seat.backend is not None, "_run_attempt is only called for mcp seats; native tasks use prepare_native"
        attempt = await self._free_attempt(ctx, task.task_id, attempt, execution_id)
        manager = self._manager_for(ctx, task.task_id, attempt, execution_id)
```
**Why**: rebinding `attempt` once at entry makes the returned `AttemptRecord`, branch and path agree.

### `models.py` / `telemetry.py` (MODIFY)
```python
# REPLACE `attempt: int = Field(..., ge=1, le=3)` — models.py occurrences: 1 (line 391); telemetry.py occurrences: 2 (lines 52, 90)
    attempt: int = Field(..., ge=1, le=20)
```

### `test_engine_dispatch.py` (MODIFY — append)
```python
async def test_run_attempt_skips_a_leftover_attempt_branch(git_sandbox_feature, noop_probe):
    """issue:3b913ffd77cd — a kept `-a1` branch must not make the re-dispatch collide."""
    worktree, feature_branch, base_path, _index_path = git_sandbox_feature
    # FILL IN: await _git("branch", f"{feature_branch}--TASK-0001-a1", cwd=str(worktree))
    # FILL IN: engine as in test_engine_attempt_cwd_is_task_branch; run_chunk ["TASK-0001"]; wait
    # FILL IN: assert outcome merged, attempts[0].attempt == 2, worktree_path ends with "TASK-0001-a2"


def test_attempt_record_accepts_attempt_above_three():
    # FILL IN: AttemptRecord(attempt=4, seat_label="a", started_at="2026-11-05T00:00:00+00:00") validates
```

### FILL IN checklist
- [ ] `_free_attempt` body (used-set, keep-requested-when-free, cap fallback)
- [ ] leftover-branch test
- [ ] AttemptRecord bound test

---

## Acceptance Criteria

- [ ] AC4: a leftover `…-a1` branch → attempt 2 used, no `git worktree add` failure.
- [ ] AC5: no leftovers → attempt 1 (existing test stays green).
- [ ] AC5b: attempt numbers up to 20 validate in `AttemptRecord` and telemetry rows.
- [ ] Existing `test_engine_dispatch.py` stays green.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`

---

## Test Specification

See blueprint.

## Agent Instructions

Touch only the four files listed. Run with `PYTHONPATH=packages/ai-parrot/src` inside the worktree.

## Completion Note

*(filled in on completion)*
