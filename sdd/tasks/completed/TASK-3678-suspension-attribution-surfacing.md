# TASK-3678: Surface suspension attribution (AC-12) in pool views and coder_plan

**Feature**: FEAT-599 — sdd-coder engine fixes 2 (suspension attribution + pool encapsulation + settlement hygiene)
**Spec**: `sdd/specs/sdd-coder-engine-fixes-2.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3677
**Assigned-to**: agent:sdd-fix
**discovered_from**: issue:bd1c792a5afc

---

## Context

Spec §1 item 1 / §2 M2. `render_suspension_history()` has no production
caller and no tool response says which task/execution caused a suspension,
so the sdd-worker cannot print what its prompt requires (FEAT-559 AC-12).
Attribution lives in `SuspensionRecord` (`task_id`/`probe_uid`,
`execution_id`, `source`); the pool already receives every record it
suspends with, and `begin_execution` already reads the `recent` durable
records — they just never reach the views.

## Scope

- `models.py`: `PoolSeatView` + `suspension_source`, `source_task_id`,
  `source_execution_id`; `ExecutionPoolView` + `suspension_summary`;
  `CoderPlan` + `suspension_summary`.
- `pool.py`: `inherited_records` kwarg, `_suspension_records`, attribution in
  `__init__` and `suspend()`, `suspension_summary` in `view()`.
- `engine.py`: `_roster_model_keys()` helper; pass `inherited_records=recent`
  on the fresh path; best-effort `recent` lookup on the restore path;
  `CoderPlan.suspension_summary` at both construction sites.
- Tests: pool-level attribution + engine-level `plan()` summary.

**NOT in scope**: compact projection (`views.py`); changing exclusion
selection; pool public API (TASK-3679).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py` | MODIFY | additive fields |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py` | MODIFY | records + attribution + summary |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | pass records; plan summary |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_pool.py` | MODIFY | attribution tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_suspension_attribution.py` | CREATE | engine `plan()` summary test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.coder_suspensions import render_suspension_history, SuspensionRecord, ModelKey  # verified: coder_suspensions.py:350,109,87
from parrot.flows.dev_loop.sdd_coder.pool import ExecutionPool  # verified: pool.py:84
from parrot.flows.dev_loop.sdd_coder.models import PoolSeatView, ExecutionPoolView, CoderPlan  # verified: models.py:428,453,280
```

### Existing Signatures to Use
```python
def render_suspension_history(records: Sequence[SuspensionRecord], now: datetime, max_tokens: int = 1200) -> str  # coder_suspensions.py:350
async def CoderSuspensionStore.recent(self, keys: list[ModelKey], now: datetime) -> list[SuspensionRecord]      # :332
# SuspensionRecord: suspension_id, execution_id, task_id|None, probe_uid|None, source, reason, expires_at, blocked_keys
# pool.py
class ExecutionPool.__init__(self, *, execution_id, feature_id, worktree_path, roster, seats, suspension_store, initial_exclusions)  # :93
def view(self) -> ExecutionPoolView   # :186
async def suspend(self, record: SuspensionRecord) -> SuspensionReceipt  # :303 — seat_view attribution block at :313-320
# engine.py
recent = await self._suspension_store.recent(model_keys, now)   # :747 (fresh path); model_keys built :727-745
pool = ExecutionPool(...)  # :674 (restore path), :763 (history-unavailable path), :785 (fresh path)
return CoderPlan(  # :1482 (exhausted early return, pool path)
result = CoderPlan(  # :1593 (normal return)
```

### Does NOT Exist
- ~~`ExecutionPool.records` / `suspension_records` property~~ — keep the list private; only `view()` renders it.
- ~~`render_suspension_history` accepting `None` for `now`~~ — always pass an aware UTC datetime.
- ~~`CoderPlan.pool` / nested `ExecutionPoolView` inside `CoderPlan`~~ — add the flat string field only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_pool.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_suspension_attribution.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/pool.py#ExecutionPool",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#PoolSeatView",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#ExecutionPoolView",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#CoderPlan",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_suspensions.py#render_suspension_history",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.begin_execution",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py#SddCoderEngine.plan"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Models first (additive, defaulted) — *why*: pool and engine compile against them.
2. Pool: store records, attribute seats, render in `view()` — *why*: the pool is the single owner of suspension state (spec §2).
3. Engine: share the model-key list via `_roster_model_keys()`, pass `inherited_records`, fill `CoderPlan.suspension_summary` — *why*: AC2/AC3.
4. Tests.

### `models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    suspended_until: str = ""' models.py)
# AFTER — insert below `    suspended_until: str = ""` (verified: models.py:450)
    suspension_source: str = ""
    """FEAT-599: `SuspensionRecord.source` of the incident that suspended this seat."""
    source_task_id: str = ""
    """FEAT-599: task id (or probe uid) whose attempt caused the suspension."""
    source_execution_id: str = ""
    """FEAT-599: execution that recorded the suspension."""

# occurrences: 1 (verified: grep -c 'FEAT-588 advisory notes about unavailable complex-task retry capacity' models.py)
# AFTER — insert below that docstring line (verified: models.py:474)
    suspension_summary: str = ""
    """FEAT-599 (FEAT-559 AC-12): bounded `render_suspension_history()` text — display only."""

# occurrences: 1 (verified: grep -c 'rejects a stale plan (`plan_stale`) once the generation has moved on' models.py)
# AFTER — insert below that docstring line (verified: models.py:301)
    suspension_summary: str = ""
    """FEAT-599 (FEAT-559 AC-12): same text as `ExecutionPoolView.suspension_summary`."""
```

### `pool.py` (MODIFY)
```python
# __init__: add kwarg `inherited_records: Sequence[SuspensionRecord] = ()` (import Sequence, datetime, timezone, render_suspension_history)
# AFTER the seat-view construction loop (verified anchor: `self._seat_views: Dict[ModelKey, PoolSeatView] = {}` pool.py:143, occurrences: 1)
        self._suspension_records: List[SuspensionRecord] = list(inherited_records)
        for record in self._suspension_records:
            self._attribute_seats(record, inherited=True)

    def _attribute_seats(self, record: SuspensionRecord, *, inherited: bool) -> None:
        """Copy *record*'s attribution onto every seat view it blocks (FEAT-599 / AC-12)."""
        origin = record.task_id or record.probe_uid or ""
        for key in record.blocked_keys:
            seat_view = self._seat_views.get(key)
            if seat_view is None:
                continue
            seat_view.suspension_source = record.source
            seat_view.source_task_id = origin
            seat_view.source_execution_id = record.execution_id
            if inherited:
                seat_view.suspension_id = record.suspension_id
                seat_view.suspended_until = record.expires_at.isoformat()

# suspend(): occurrences: 1 (verified: grep -c 'seat_view.suspended_until = record.expires_at.isoformat()' pool.py)
# AFTER the `for key in record.blocked_keys:` loop inside `async with self._condition:` — append record then attribute:
            self._suspension_records.append(record)
            self._attribute_seats(record, inherited=False)

# view(): occurrences: 1 (verified: grep -c 'roster_warnings=self._roster_warnings(),' pool.py)
# AFTER — add field
            suspension_summary=render_suspension_history(self._suspension_records, datetime.now(timezone.utc)),
```
**Why**: inherited seats keep `reason="inherited_suspension"` (existing contract) but gain the incident id/expiry now that the record is known.

### `engine.py` (MODIFY)
```python
# 1. Extract engine.py:727-745 (the `model_keys = []` loop) into:
    def _roster_model_keys(self) -> List[ModelKey]:
        """Every primary/native/fallback identity in the roster, for durable-history lookups (FEAT-559 AC-4)."""
        # FILL IN: move the loop body verbatim; return model_keys
# 2. fresh path: `recent = await self._suspension_store.recent(self._roster_model_keys(), now)`; pass `inherited_records=recent` to ExecutionPool(...) at :785
# 3. restore path (:674): before constructing the pool:
                inherited_records: List[SuspensionRecord] = []
                try:
                    inherited_records = await self._suspension_store.recent(self._roster_model_keys(), now)
                except Exception as exc:  # noqa: BLE001 — attribution is display-only; exclusions come from the snapshot
                    self.logger.warning("suspension attribution unavailable while restoring %s: %s", execution_id, exc)
#    then pass `inherited_records=inherited_records`
# 4. plan(): at :1482 add `suspension_summary=pool.view().suspension_summary,`; at :1593 add
#    `suspension_summary=pool.view().suspension_summary if pool is not None else "",`
#    (FILL IN: confirm the variable name bound to the execution pool in that scope — bounded by spec §2 M2)
```

### `test_pool.py` (MODIFY) — append
```python
@pytest.mark.asyncio
async def test_suspend_sets_seat_attribution(...):  # FILL IN — AC3
def test_inherited_records_attribute_seats_and_summary(...):  # FILL IN — AC3 + AC2 (summary contains record.suspension_id)
```

### `test_suspension_attribution.py` (CREATE)
```python
"""FEAT-599 / issue:bd1c792a5afc: suspension attribution reaches coder_plan (FEAT-559 AC-12)."""
# FILL IN: reuse the engine/worktree fixtures pattern from test_outstanding_jobs.py; begin_execution with an mcp seat,
#   admit an attempt via pool.admit, engine.suspend_model(execution_id, attempt_uid, "review_critical", "ref"),
#   plan = await engine.plan(feature, worktree, execution_id=execution_id)
#   assert "TASK-1" in plan.suspension_summary and execution_id in plan.suspension_summary
#   (if plan() needs a scheduler/index, write a minimal index with one pending task) — bounded by AC2
```

### FILL IN checklist
- [ ] `_roster_model_keys` extraction — behavior-preserving
- [ ] `plan()` pool variable name at :1593
- [ ] test bodies — AC2, AC3

---

## Acceptance Criteria

- [ ] AC2: `ExecutionPoolView.suspension_summary` and `CoderPlan.suspension_summary` are non-empty after a suspension and include incident id, model, source task/execution, reason, remaining cooldown.
- [ ] AC3: suspended `PoolSeatView` carries `suspension_source`, `source_task_id`, `source_execution_id`; inherited suspensions are attributed.
- [ ] existing `test_pool.py`, `test_suspensions.py`, `test_execution_pool_integration.py` still pass.
- [ ] `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_pool.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_suspension_attribution.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_suspensions.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_execution_pool_integration.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_dispatch.py -q`

---

## Completion Note

**Completed by**: Claude Fable 5.1 via `/sdd-fix`
**Date**: 2026-09-24

- `PoolSeatView` += `suspension_source` / `source_task_id` / `source_execution_id`; `ExecutionPoolView` and `CoderPlan` += `suspension_summary` (rendered by `render_suspension_history`, now with a production caller).
- `ExecutionPool(inherited_records=...)` keeps every known record (inherited + own), attributes seat views on construction and in `suspend()`, renders the summary in `view()`.
- Engine: `_roster_model_keys()` extracted; fresh path passes `recent`, restore path looks records up best-effort; `plan()` fills `CoderPlan.suspension_summary` on both return paths.
- Tests: `test_pool.py` +3, new `test_suspension_attribution.py` (+2: plan summary after `suspend_model`; new engine on the same worktree inherits the attribution through the durable ledger).
- Validation: pool/suspensions/attribution/integration/dispatch/plan_merge/toolkit/outstanding → 155 passed, 1 failed. The one failure, `test_engine_plan_merge.py::test_all_seats_exhausted`, fails identically on `origin/dev` (main checkout, same assertion) — pre-existing, not introduced here.
- Note: an inherited-excluded identity is filtered before the probe (AC-4), so it has no seat view; the summary is the attribution channel for it.
