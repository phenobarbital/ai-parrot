# TASK-3578: Delete the unreachable `dirty_task_worktree` paths in the engine and its error-code enum

**Feature**: FEAT-587 — Retire the `dirty_task_worktree` contract
**Spec**: `sdd/specs/fixgroup-05941da3dd5f.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**discovered_from**: `issue:88b5c7d679c1`

---

## Context

A coder seat runs sandboxed with `.git` **read-only by design**: it delivers its
work in the attempt worktree and cannot commit it. Producing the commit is the
orchestrator's job. Commit `ed267c217` made that true — `_consolidate` now calls
`_commit_declared_changes` (`engine.py:2069`, call site `:2179`), which stages
only the task markdown's declared files and commits them on the attempt branch.

That fix orphaned the contract around it. `_consolidate` can no longer return
`outcome="failed"` with a `dirty_task_worktree:`-prefixed diagnostic, so the
guard in `_run_task` that tests for exactly that is **unreachable**, and with it
the cross-seat retry and the `dirty_delivery` suspension reason whose only
producer was that dead branch. The MCP `ERROR_CODES` frozenset still advertises
an error code the server can never return.

This is not cosmetic: the next agent to touch `_run_task` will reason from a
contract that no longer holds, and `dirty_delivery` reads like a live suspension
path that could still charge a model for behaving correctly.

## Scope

Delete the two unreachable paths in `engine.py`, correct the `_run_task`
docstring that advertises them, drop `"dirty_task_worktree"` from `ERROR_CODES`,
and add the two regression tests that keep the contract from creeping back.

**NOT in scope**:
- `_commit_declared_changes` and `_consolidate` — they shipped in `ed267c217`
  and their tests pass. Do not touch their logic.
- `"dirty_delivery"` in `coder_suspensions.py:49` — deliberately **kept** so
  ledger rows written before `ed267c217` still parse (spec AC-5, §8 Q1).
- `"dirty_feature_worktree"` (`models.py:59`) — a different, still-live
  precondition on the *feature* worktree.
- Documentation and FEAT-549's AC-22 — those are TASK-3579.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | Delete the dead guard + retry assignment in `_run_task`; delete the `dirty_delivery` branch in `_classify_failure_reason`; correct the `_run_task` docstring |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | Remove `"dirty_task_worktree"` from `ERROR_CODES` |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` | MODIFY | Add the two regression tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` on 2026-09-21.

### Verified Imports

```python
from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine  # verified: sdd_coder/engine.py
from parrot.flows.dev_loop.sdd_coder.models import ERROR_CODES     # verified: sdd_coder/models.py:46
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py
class SddCoderEngine:
    def _classify_failure_reason(                 # line 2888
        self, error: str, error_class: str, outcome: Optional[str] = None
    ) -> Optional[str]: ...
    async def _run_task(                          # lines 3155-3305
        self, ctx: _FeatureCtx, task: PlannedTask, seat: RosterSeat, *,
        job_id: str, execution_id: Optional[str] = None, pool: Optional["ExecutionPool"] = None,
    ) -> TaskResult: ...
    async def _commit_declared_changes(...)       # line 2069 — DO NOT MODIFY (ed267c217)

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
ERROR_CODES: frozenset[str] = frozenset({...})    # line 46; "dirty_task_worktree" at line 60
```

Existing `_classify_failure_reason` tests to sit beside:
`packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py:788-860`.

### Does NOT Exist

- ~~`SddCoderEngine._suspension_reason`~~ — the classifier is **`_classify_failure_reason`** (`engine.py:2888`).
- ~~`test_engine_rejects_dirty_task_worktree`~~ — removed by `ed267c217`. Do **not** restore it. It survives only in `packages/ai-parrot/build/` and in `.claude/worktrees/feat-FEAT-564-…--pool/`, neither of which is a source of truth.
- ~~`packages/ai-parrot/build/lib.linux-x86_64-cpython-312/…/engine.py`~~ — stale build artifact carrying the pre-`ed267c217` code. Never edit it; scope every grep to `packages/ai-parrot/src` and `packages/ai-parrot/tests`.
- ~~a `dirty_delivery` assertion in the current test suite~~ — none exists, so removing the branch breaks no test.

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
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_task",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._classify_failure_reason",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._consolidate"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Deletions only. Do not "improve" adjacent logic while you are in the file.
- 120-column lines; `black` formats, `ruff check` is the gate.
- `self.logger`, never `print`.

### References in Codebase
- `mem-c163c2dde8ff` — the decision record: `.git` is read-only to a seat by design.
- `ed267c217` — the commit that made the engine extract and commit.

---

## Implementation Blueprint

### Steps (in order)

1. `engine.py` — collapse the dead guard in `_run_task`, because `_consolidate`
   has no code path left that produces a `dirty_task_worktree:` diagnostic, so
   the `if` is always true and the `else` fall-through is unreachable.
2. `engine.py` — delete the `dirty_delivery` branch in
   `_classify_failure_reason`, because step 1 removed its only producer; leaving
   it would let a future `error_class` string silently re-enable a suspension
   for correct behaviour.
3. `engine.py` — rewrite the `_run_task` docstring paragraph, because it is the
   contract the next agent reads.
4. `models.py` — drop the enum member, because the server can no longer return it.
5. `test_engine_dispatch.py` — add both regression tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY — step 1)

```python
# occurrences: 1 (verified: grep -c 'if not (result.outcome == "failed" and result.diagnostics.startswith("dirty_task_worktree:")):' engine.py)
# REPLACE the guard at engine.py:3186 and the three lines at :3199-3201.
# BEFORE (delete all of this):
#     if not (result.outcome == "failed" and result.diagnostics.startswith("dirty_task_worktree:")):
#         final_result = result.model_copy(update={"attempts": attempts, "development_output": out})
#         ...
#         return final_result
#
#     err = result.diagnostics
#     rec = rec.model_copy(update={"error": err, "error_class": "dirty_task_worktree"})
#     attempts[-1] = rec
# AFTER — the body runs unconditionally, one indent level shallower:
        if not err:
            result = await self._consolidate(ctx, manager, task, branch=branch, path=path)
            final_result = result.model_copy(update={"attempts": attempts, "development_output": out})
            self._latest_attempt[task.task_id] = rec
            await self._emit_outcome(
                ctx,
                attempt_rec=rec,
                task_id=task.task_id,
                outcome=result.outcome,
                conflict_file_count=len(result.conflict_files),
                unexpected_file_count=len(result.unexpected_files),
            )
            return final_result
```

**Why this shape**: a consolidation result is now always terminal — merged,
`fidelity_violation`, `merge_conflict` or `failed` — and each is the
orchestrator's to handle, not a reason to burn the second attempt on another
seat. The `if err:` block that follows is reached only from the dispatch-error
path, which is already how it behaves in practice. What must NOT change: the
`_emit_outcome` call and its arguments, and the `self._latest_attempt` write.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY — step 2)

```python
# occurrences: 1 (verified: grep -c '# Check for dirty delivery' engine.py)
# DELETE these three lines at engine.py:2907-2909:
#         # Check for dirty delivery
#         if error_class == "dirty_task_worktree" or (error and error.startswith("dirty_task_worktree:")):
#             return "dirty_delivery"
```

**Why**: its only producer was the assignment deleted in step 1. Keep the
`fidelity_violation` check above it and the timeout check below it untouched —
both are live.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` (MODIFY — step 3)

```python
# occurrences: 1 (verified: grep -c '``dirty_task_worktree`` outcome as retryable, but preserve fidelity' engine.py)
# REPLACE the docstring paragraph at engine.py:3167-3171 with:
        """Run up to two attempts, retrying DISPATCH failures on another MCP seat.

        A seat that delivers its declared files without committing them is not a
        failure: ``.git`` is read-only to a sandboxed seat by design, and
        ``_consolidate`` extracts and commits the deliverable itself via
        ``_commit_declared_changes`` (ed267c217 / FEAT-587). Only dispatch errors
        are retried on a fresh seat; fidelity violations and merge conflicts are
        preserved for the orchestrator to handle.

        FEAT-559: When execution_id/pool are provided, uses pool-based admission
        gating, failure classification, and healthy-model retry selection.
        """
```

**Why**: the summary line and the paragraph both claimed a retryable
`dirty_task_worktree` outcome that can no longer occur. Keep the FEAT-559
paragraph verbatim — it is still accurate.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` (MODIFY — step 4)

```python
# occurrences: 1 (verified: grep -c '"dirty_task_worktree",' models.py)
# DELETE the single line at models.py:60:
#         "dirty_task_worktree",
# The line above it, "dirty_feature_worktree", MUST stay — different precondition.
```

**Why**: `ERROR_CODES` is the MCP surface contract; advertising a code the server
cannot return misleads every client that switches on it.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py` (MODIFY — step 5)

```python
# occurrences: 1 (verified: grep -c 'reason = engine._classify_failure_reason(' -m1 test_engine_dispatch.py — 6 call sites, all inside the existing classifier test class)
# AFTER — append beside the existing _classify_failure_reason cases (:788-860):

def test_no_dirty_task_worktree_producer() -> None:
    """No engine path may produce the retired `dirty_task_worktree` contract."""
    # FILL IN: read both module sources via importlib.util.find_spec / Path and
    # assert "dirty_task_worktree" is absent — bounded by AC-1 and AC-4: a match
    # inside a comment that explains the retirement is allowed, a match in code
    # is not. Scope the read to packages/ai-parrot/src only, never build/.


def test_classify_failure_reason_ignores_uncommitted_delivery() -> None:
    """An uncommitted-but-declared delivery is never charged against the model."""
    # FILL IN: build the engine the way the neighbouring classifier tests do,
    # then assert `_classify_failure_reason` returns None for the error shape
    # that previously classified as "dirty_delivery" — bounded by AC-3.
    # Also assert a genuine timeout still classifies as "timeout", so the test
    # cannot pass by the classifier returning None for everything.
```

**Why**: AC-1 is the guard that keeps the contract from creeping back in a future
edit; the second test pins the behavioural consequence. Follow the construction
and fixtures the existing tests at `:788-860` already use — do not invent a new
engine fixture.

### FILL IN checklist

- [ ] `test_no_dirty_task_worktree_producer` — how the two module sources are located and read (AC-1, AC-4)
- [ ] `test_classify_failure_reason_ignores_uncommitted_delivery` — engine construction copied from the neighbouring tests, plus the `"timeout"` control assertion (AC-3)

---

## Acceptance Criteria

- [ ] `grep -rn "dirty_task_worktree" packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/` returns no hit outside a comment explaining the retirement (AC-1)
- [ ] `_run_task` returns the consolidation result unconditionally when `_run_attempt` reported no dispatch error; no retry is burned for an uncommitted-but-declared delivery (AC-2)
- [ ] `_classify_failure_reason` has no `dirty_delivery` branch, and no code path assigns `error_class="dirty_task_worktree"` (AC-3)
- [ ] `dirty_task_worktree` is absent from `ERROR_CODES`; `dirty_feature_worktree` still present (AC-4)
- [ ] `coder_suspensions.py` is unmodified — `SuspensionReason` still accepts `"dirty_delivery"` (AC-5)
- [ ] The three integration tests named in spec §4 pass **unmodified** (AC-8)
- [ ] `ruff check` and `black --check` clean on every changed file (AC-9)

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_integration_chunk.py -q`

## Test Specification

The three integration tests below already exist and must pass **without being
edited** — they encode the behaviour this task aligns the contract to:

- `test_integration_chunk.py::test_uncommitted_declared_work_is_extracted_and_merged` (`:164`)
- `test_engine_plan_merge.py::test_engine_commits_uncommitted_declared_work` (`:154`)
- the undeclared-leftover case at `test_engine_plan_merge.py:132-149`

Editing any of them to make this task pass is a scope violation: they are the
specification of the shipped behaviour.

---

## Completion Note

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
