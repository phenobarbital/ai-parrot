# TASK-3677: Lazy attempt number in snapshot enrichment + settlement regression test

**Feature**: FEAT-599 — sdd-coder engine fixes 2 (suspension attribution + pool encapsulation + settlement hygiene)
**Spec**: `sdd/specs/sdd-coder-engine-fixes-2.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: agent:sdd-fix
**discovered_from**: issue:c1e28856ab0c, issue:5944887877e1, issue:971e11917b19

---

## Context

Spec §1 item 2 / §2 M1. `end_execution` (engine.py:910) and the `status()`
persistence retry (engine.py:2844) both evaluate
`self._latest_attempt.get(task_id, AttemptRecord(attempt=1))`. The default is
evaluated eagerly and `AttemptRecord` requires `seat_label` and `started_at`,
so the expression raises `pydantic.ValidationError` on every iteration of the
native-reservation loop. Native tasks never populate `_latest_attempt`, so the
crash is reachable whenever the loop runs with a native reservation present
(idempotent re-close of a `closed` pool; degraded persistence retry).

`issue:5944887877e1` and `issue:971e11917b19` report the pre-FEAT-594
"outstanding jobs never empty" defect. FEAT-594 / TASK-3670 (commit
`d40f43e82`) fixed it; this task pins the *published settlement artifact*
contract they describe with one regression test.

## Scope

- Add `SddCoderEngine._latest_attempt_number(task_id) -> int`.
- Use it at both `manager_key` sites.
- Add three tests to `test_outstanding_jobs.py` (spec §4 M1 rows).

**NOT in scope**: pool API changes (TASK-3679), suspension attribution (TASK-3678).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | helper + 2 call sites |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_outstanding_jobs.py` | MODIFY | 3 regression tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.sdd_coder.engine import CoderFailure, SddCoderEngine  # verified: test_outstanding_jobs.py:20
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat, TaskResult  # verified: test_outstanding_jobs.py:21
```

### Existing Signatures to Use
```python
# engine.py
self._latest_attempt: Dict[str, AttemptRecord]           # :413
self._native_reservations: Dict[Tuple[str, str], str]    # (execution_id, task_id) -> attempt_uid
self._manager_execution: Dict[str, str]                  # "<task>.a<n>" -> execution_id
async def end_execution(self, execution_id: str) -> "ExecutionPoolView"   # :841
async def status(self, job_id: str) -> CoderJob                            # ~:2812
self._evidence_store  # ExecutionEvidenceStore | None; put_artifact(execution_id, snapshot); get_artifact(execution_id)
# test_outstanding_jobs.py helpers: _engine(tmp_path), _register_job(engine, worktree, execution_id, gate), _begin(engine, tmp_path)
```

### Does NOT Exist
- ~~`AttemptRecord` with defaults for `seat_label`/`started_at`~~ — both required.
- ~~a public "attempt number" accessor on the engine~~ — this task creates the private helper.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_outstanding_jobs.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.end_execution",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.status"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the helper directly above `_outstanding_job_ids` — *why*: same "engine bookkeeping read" family, one definition for both enrichment loops.
2. Replace both `manager_key` expressions — *why*: never construct an under-specified `AttemptRecord` (AC1).
3. Add the three tests — *why*: the re-close and degraded-retry paths are the only ones that reach the loop; the settlement test pins FEAT-594's artifact contract (AC5).

### `engine.py` (MODIFY) — helper
```python
# occurrences: 1 (verified: grep -c '    def _outstanding_job_ids(self, execution_id: str, worktree: str) -> List\[str\]:' engine.py)
# BEFORE — insert above `    def _outstanding_job_ids(self, execution_id: str, worktree: str) -> List[str]:` (verified: engine.py:808)
    def _latest_attempt_number(self, task_id: str) -> int:
        """Return the attempt number of *task_id*'s latest recorded attempt, or ``1``.

        Native dispatch never records into ``_latest_attempt`` (that
        bookkeeping lives in ``_run_task``), so a missing entry means "first
        attempt" -- never a reason to build a placeholder ``AttemptRecord``
        (issue:c1e28856ab0c: ``dict.get``'s default is evaluated eagerly and
        ``AttemptRecord`` requires ``seat_label``/``started_at``).

        Args:
            task_id: The task whose manager key is being derived.

        Returns:
            The recorded attempt number, or ``1`` when none exists.
        """
        record = self._latest_attempt.get(task_id)
        return record.attempt if record is not None else 1
```

### `engine.py` (MODIFY) — call sites
```python
# occurrences: 1 (verified: grep -c 'manager_key = f"{task_id}.a{self._latest_attempt.get(task_id, AttemptRecord(attempt=1)).attempt}"' engine.py)
                manager_key = f"{task_id}.a{self._latest_attempt_number(task_id)}"
# occurrences: 1 (verified: grep -c 'f"{task_id}.a{self._latest_attempt.get(task_id, AttemptRecord(attempt=1)).attempt}"' engine.py)  — status() retry, multi-line parenthesised
                        manager_key = f"{task_id}.a{self._latest_attempt_number(task_id)}"
```
**Why**: `AttemptRecord` stays imported (used elsewhere); only the eager default goes.

### `test_outstanding_jobs.py` (MODIFY) — append
```python
@pytest.mark.asyncio
async def test_end_execution_reclose_with_native_reservation_does_not_raise(tmp_path: Path) -> None:
    """Idempotent re-close reaches the enrichment loop; a native task without a recorded attempt maps to .a1 (AC1)."""
    # FILL IN: engine=_engine(tmp_path); execution_id, wt = await _begin(...)
    #   pool = engine._executions[execution_id]; await pool.close()
    #   engine._native_reservations[(execution_id, "TASK-1")] = "uid"; engine._manager_execution["TASK-1.a1"] = execution_id
    #   view = await engine.end_execution(execution_id)  -> no ValidationError; view.status == "closed"
    #   assert (await engine._evidence_store.get_artifact(execution_id)).native_reservations["TASK-1"] == "TASK-1.a1"  (or read the in-worktree snapshot)


@pytest.mark.asyncio
async def test_status_persistence_retry_with_native_reservation(tmp_path: Path) -> None:
    """Degraded persistence retry never constructs an AttemptRecord (AC1)."""
    # FILL IN: same reservation setup; pool._persistence_degraded = True; register a job; await engine.status(job_id)


@pytest.mark.asyncio
async def test_settlement_artifact_after_done_job_has_no_outstanding_ids(tmp_path: Path) -> None:
    """issue:5944887877e1 / issue:971e11917b19 — FEAT-594 settlement contract (AC5)."""
    # FILL IN: gate job via _register_job; gate.set(); await engine._jobs.wait(job_id, 5); await engine.end_execution(...)
    #   artifact = await engine._evidence_store.get_artifact(execution_id); assert artifact.outstanding_job_ids == []
```

### FILL IN checklist
- [ ] three test bodies — AC1, AC5

---

## Acceptance Criteria

- [ ] AC1: no `AttemptRecord(attempt=1)` remains in `engine.py`; both new M1 tests pass.
- [ ] AC5: settlement artifact test passes.
- [ ] `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_outstanding_jobs.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_review_checkpoint.py -q`

---

## Completion Note

**Completed by**: Claude Fable 5.1 via `/sdd-fix`
**Date**: 2026-09-24

- Added `SddCoderEngine._latest_attempt_number()`; both `manager_key` sites use it — no `AttemptRecord(attempt=1)` literal remains in `engine.py`.
- `test_outstanding_jobs.py`: +3 tests (re-close with native reservation, `status()` degraded retry, published settlement after a `done` job).
- Validation: `test_outstanding_jobs.py` + `test_review_checkpoint.py` + `test_execution_pool_integration.py` → 23 passed; `ruff check` clean. `black --check` reports one pre-existing wrap at engine.py:1953 (also present on `origin/dev`), left untouched.
