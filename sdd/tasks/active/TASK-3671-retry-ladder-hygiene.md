# TASK-3671: Retry-ladder hygiene (native retry docstring, vacuous all(), dead plan() branch)

**Feature**: FEAT-594 — sdd-coder engine fixes (settlement outstanding jobs + retry-ladder hygiene)
**Spec**: `sdd/specs/sdd-coder-engine-fixes.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3670
**Assigned-to**: unassigned
**discovered_from**: issue:466c3bcd0c9a, issue:8cfe91c4adf5, issue:0e6daa941b57, issue:fffc637dfc99

---

## Context

Spec §3 Module 2. Four small, behavior-preserving fixes in `engine.py`
filed from the FEAT-561/FEAT-588 reviews.

## Scope

- `_select_native_retry_seat` (engine.py:3158): Google-style docstring with
  Args/Returns, plus a paragraph on why it never waits on a busy native seat
  (`issue:466c3bcd0c9a`, `issue:0e6daa941b57`).
- `_run_task` MCP-only diagnostic (engine.py:3393-3398): no vacuous `all()`
  over an empty candidate set (`issue:8cfe91c4adf5`).
- `plan()` (engine.py:1509-1512): remove the unreachable
  `complexity_plan_stale` re-raise (`issue:fffc637dfc99`).

**NOT in scope**: adding a busy-wait to the native selector; any change to
`_compute_assessment`'s raised codes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | 3 local edits |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# engine.py:3158
async def _select_native_retry_seat(self, pool: Optional["ExecutionPool"], tried_seats: set[str], *,
                                    eligible_labels: Optional[Set[str]] = None) -> Optional[RosterSeat]
# engine.py:3191 — _select_retry_seat: the MCP selector, which DOES `await pool._condition.wait()` on a busy healthy seat
# engine.py:2387 — merge(): the only place a native reservation's seat is released (pool.release at :2432)
# engine.py:1610 — _compute_assessment raises only "complexity_contract_invalid" / "complexity_audit_failed"
```

### Does NOT Exist
- ~~`complexity_plan_stale` raised by `_compute_assessment`~~ — only `_assessment_for` (engine.py:~1575) raises it, and `plan()` never calls that inside this try.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._select_native_retry_seat",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine._run_task",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.plan"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Replace the one-line docstring — *why*: codebase convention (Google style) and to record the no-wait design choice.
2. Materialize the candidates before `all()` — *why*: `all()` of an empty generator is `True`, mislabeling the diagnostic as "MCP-only".
3. Drop the dead branch — *why*: unreachable code misleads readers about what the loop can raise.

### `engine.py` (MODIFY) — docstring
```python
# occurrences: 1 (verified: grep -c '(FEAT-588)."""' engine.py)
# REPLACE `        """Return an untried, healthy eligible native seat, or ``None`` (FEAT-588)."""` (engine.py:3165)
        """Return an untried, healthy eligible native seat, or ``None`` (FEAT-588).

        Unlike `_select_retry_seat`, this never waits on a busy seat: a native
        seat is released only by the orchestrator's `merge()` of its
        reservation, which may itself be sequenced after this job's
        `coder_wait`, so waiting here could park the job until the wait
        timeout. A busy native seat is treated as unavailable and the caller
        emits the explicit `complex_model_unavailable` block instead.

        Args:
            pool: The execution pool, or None for the legacy path (always None).
            tried_seats: Seat labels already attempted for this task.
            eligible_labels: Optional restriction to the task's eligible label set.

        Returns:
            A free, healthy native RosterSeat, or None when none qualifies.
        """
```

### `engine.py` (MODIFY) — vacuous all()
```python
# occurrences: 1 (verified: grep -c 'and all(candidate.kind == "native" for candidate in pool._seats if candidate.label in remaining)' engine.py)
# FILL IN: rewrite the `if (pool is not None and remaining and all(...))` condition so the
#   candidate list `[c for c in pool._seats if c.label in remaining]` is built first and the
#   MCP-only message is chosen only when that list is non-empty AND all native — bounded by
#   no change to either message text
```

### `engine.py` (MODIFY) — dead branch
```python
# occurrences: 1 (verified: grep -c 'if exc.code == "complexity_plan_stale":' engine.py)
# REMOVE engine.py:1510-1512 (`if exc.code == "complexity_plan_stale":` / comment / `raise`);
# FILL IN: adjust the following comment so it no longer says "Any other" — bounded by no behavior change
```

### FILL IN checklist
- [ ] vacuous-all rewrite
- [ ] dead-branch removal + comment wording

---

## Acceptance Criteria

- [ ] Docstring has Args/Returns and the no-wait rationale.
- [ ] MCP-only diagnostic only when the candidate set is non-empty and all native.
- [ ] No `complexity_plan_stale` branch inside `plan()`'s per-task `except CoderFailure`.
- [ ] `ruff check` clean on engine.py.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_routing.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_plan_merge.py -q`

---

## Completion Note

*(Agent fills this in when done)*
