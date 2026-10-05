# TASK-4103: Manager delivery outcome collection and persistence

**Feature**: FEAT-635 — Scheduler callback delivery status
**Spec**: `sdd/specs/scheduler-callback-delivery-status.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 2** (GitHub issue #1574). Today `AgentSchedulerManager._handle_job_success`:
- throws away each callback's return value;
- lets one raising callback skip every later callback and `send_result`;
- ignores `_send_result_email`'s notifier status.

`_process_job_success` stamps `last_status="success"` before callbacks run and only logs their errors. This task runs each callback independently, collects one outcome per delivery, and saves the delivery status in `metadata`, without changing `last_status`.

This task does **not** import anything from TASK-4102. It relies only on the `status` key convention (`sent | saved | partial | failed`, plus NotificationMixin's `success | error`), so the two tasks run concurrently.

---

## Scope

- Change `_handle_job_success` to return `List[Dict[str, Any]]`.
  - Run each callback definition in its own `try`; a build error or raised exception becomes a `failed` outcome, and the loop continues.
  - Run `send_result` in its own `try` too.
  - `success_callback` behaves as before and is **not** recorded.
- Change `_send_result_email` to return the notifier dict, or `None` on its two early-return paths.
- Add the static helpers `_callback_outcome(name, response=None, error=None)` and `_aggregate_delivery_status(outcomes)`.
- Add `async _stamp_delivery_outcome(schedule_id, outcomes)`, modelled on `_on_coordination_unavailable`. It writes `metadata.last_callbacks`, `last_delivery_status` and `last_delivery_time`, and never raises.
- In `_process_job_success`, capture the outcomes; when `persist` is true and outcomes are non-empty, stamp them. Log each `failed`/`partial` outcome at `warning` level with `schedule_id` and the callback name.
- Write tests in a new `test_delivery_outcomes.py`.

**NOT in scope**: `functions/__init__.py` (TASK-4102); `_update_schedule_run` (unchanged); handlers/UI; DDL.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | outcome collection, aggregation, delivery stamp |
| `packages/ai-parrot-server/tests/scheduler/test_delivery_outcomes.py` | CREATE | Unit tests for M2 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in manager.py — add nothing new:
from typing import Any, Dict, Optional, Callable, List, Tuple, Set  # verified: manager.py:14
from datetime import datetime                                       # verified: manager.py:15
from .models import AgentSchedule                                   # verified: manager.py:43
from ..notifications import NotificationMixin                       # verified: manager.py:54
from .functions import build_scheduler_callback                     # verified: manager.py:56
# Tests:
from parrot.scheduler.manager import AgentSchedulerManager          # verified: tests/scheduler/test_listeners.py:10
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/scheduler/manager.py
class _SchedulerNotification(NotificationMixin):  # line 342 — __init__(self, logger)
class AgentSchedulerManager:  # line 349
    async def _handle_job_success(self, schedule_id: str, agent_name: str, result: Any,
                                  success_callback: Optional[Callable], send_result: Optional[Dict[str, Any]],
                                  callbacks: Optional[List[Dict[str, Any]]] = None) -> None:  # line 732
        # loop: build_scheduler_callback(definition, logger=self.logger) then
        #   `await callback(result, schedule_id=schedule_id, agent_name=agent_name)` at :750
        # `if send_result: await self._send_result_email(...)` at :752-753
    async def _send_result_email(self, schedule_id, agent_name, result, send_result) -> None:  # line 755
        # early returns at :765 (not a dict) and :776 (no recipients)
        # `await notifier.send_email(` at :810 (result discarded)
    async def _process_job_success(self, schedule_id, agent_name, result, success_callback, send_result,
                                   callbacks=None, *, persist: bool = True) -> None:  # line 819
        # `await self._handle_job_success(` at :849, inside try/except that logs (:848-865)
    _LAST_RESULT_MAX_CHARS  # line 889
    async def _on_coordination_unavailable(self, job_id: str, exc: BaseException) -> None:  # line 952-976 — stamp pattern:
        # pool None guard → warning + return; async with await self._pool.acquire() as conn;
        # AgentSchedule.Meta.connection = conn; schedule = await AgentSchedule.get(schedule_id=...);
        # if not schedule.metadata: schedule.metadata = {}; mutate; await schedule.update();
        # except Exception → self.logger.error(...)

# packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py
def build_scheduler_callback(definition: Dict[str, Any], logger=None):  # line 210 — raises ValueError on an unknown type;
    # name comes from definition.get("type") or definition.get("name")

# packages/ai-parrot/src/parrot/notifications/__init__.py
NotificationMixin.notification_succeeded(result) -> bool  # line 303 (staticmethod)

# test fixtures to copy: packages/ai-parrot-server/tests/scheduler/test_listeners.py
#   manager fixture :13-16 (AgentSchedulerManager()); _FakePoolAcquireContext :51-62; _FakePool :64-71
```

### Does NOT Exist
- ~~`AgentSchedule.last_callbacks` / `delivery_status` columns~~: these are `metadata` keys only, so no DDL.
- ~~`_stamp_delivery_outcome`, `_callback_outcome`, `_aggregate_delivery_status`~~: they are new in this task.
- ~~a `conftest.py` under `tests/scheduler/`~~: none exists; define the fixtures inside the test file (do not create a conftest; that would make the task exclusive).
- ~~`SchedulerCallbackDeliveryError`~~: not created.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/scheduler/manager.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/scheduler/test_delivery_outcomes.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._handle_job_success",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._send_result_email",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._process_job_success",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/manager.py#AgentSchedulerManager._on_coordination_unavailable",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py#build_scheduler_callback",
    "sym:packages/ai-parrot/src/parrot/notifications/__init__.py#NotificationMixin.notification_succeeded"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `_process_job_success` runs as a fire-and-forget task, so nothing it calls may raise. Keep the outer `try/except` at `:848-865`.
- The stamp must re-`get` the row; never reuse an object from `_update_schedule_run`. Otherwise it would overwrite `last_result` (spec §7).
- Never touch `last_status`, `run_count`, `last_run` or `next_run` in the stamp (spec U2, AC5).
- Truncate each outcome's `error` to `self._LAST_RESULT_MAX_CHARS` before storing it.
- `_handle_job_success` has exactly one caller (`manager.py:849`, verified by grep).

---

## Implementation Blueprint

### Steps (in order)
1. Add `_callback_outcome` and `_aggregate_delivery_status` as `@staticmethod`s just above `_handle_job_success` (`:732`). *Why*: they are pure and easy to unit-test (spec §2).
2. Rewrite the body of `_handle_job_success` (`:732-753`) to collect outcomes. *Why*: AC3, AC4.
3. Make `_send_result_email` return values: `return None` on both early returns, and `return await notifier.send_email(...)` at `:810`; change the annotation to `Optional[Dict[str, Any]]`. *Why*: so the send_result status can be recorded.
4. Add `_stamp_delivery_outcome` directly above `_on_coordination_unavailable` (`:952`). *Why*: it reuses that pattern (AC5, AC6).
5. In `_process_job_success`, capture outcomes at `:849` and stamp/log. *Why*: AC5–AC7.
6. Write the tests and run the Validation Commands.

### `packages/ai-parrot-server/src/parrot/scheduler/manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _handle_job_success(' …/manager.py) — line :732
# INSERT above `async def _handle_job_success(`
    @staticmethod
    def _callback_outcome(name: str, response: Any = None, error: Optional[BaseException | str] = None) -> Dict[str, Any]:
        """Build one delivery outcome ``{"callback", "status", "error"}``.

        A raised ``error`` → ``failed``. A dict ``response`` → its ``status``,
        normalised: NotificationMixin ``success`` → ``sent``, ``error`` → ``failed``;
        ``sent``/``saved``/``partial``/``failed`` pass through. ``None`` or an
        unknown status → ``failed``.
        """
        # FILL IN: the mapping above; error text = str(error) when given, else
        # response.get("error") for failed/partial dicts, else None. Bounded by spec §2.
        ...

    @staticmethod
    def _aggregate_delivery_status(outcomes: List[Dict[str, Any]]) -> Optional[str]:
        """Reduce outcomes to ``ok`` | ``partial`` | ``failed``; ``None`` when empty.

        ``ok`` = every status in {sent, saved}; ``failed`` = every status failed;
        anything else (including any ``partial``) = ``partial``.
        """
        # FILL IN: per docstring; bounded by spec §2 aggregation table
        ...
```
```python
# REPLACE body of _handle_job_success (:732-753); signature return type → List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Run success_callback, every callback definition and send_result; return delivery outcomes.

        Each delivery is isolated: a failure is recorded and never prevents the
        rest. ``success_callback`` is user code, not a delivery, and is not recorded.
        """
        if success_callback:
            callback_result = success_callback(result)
            if inspect.isawaitable(callback_result):
                await callback_result

        outcomes: List[Dict[str, Any]] = []
        for definition in list(callbacks or []):
            name = str(definition.get("type") or definition.get("name") or "unknown")
            try:
                callback = build_scheduler_callback(definition, logger=self.logger)
                response = await callback(result, schedule_id=schedule_id, agent_name=agent_name)
                outcomes.append(self._callback_outcome(name, response))
            except Exception as exc:  # noqa: BLE001 — isolate each delivery (AC3)
                outcomes.append(self._callback_outcome(name, error=exc))

        if send_result:
            # FILL IN: same try/except around `await self._send_result_email(...)`; a None return
            # → failed outcome with error "send_result not sent (invalid config or no recipients)".
            # Name: "send_result". Bounded by AC3/AC4.
            ...
        return outcomes
```
```python
# occurrences: 1 (verified: grep -c '        await notifier.send_email(' …) — line :810
# REPLACE `        await notifier.send_email(` with `        return await notifier.send_email(`
# and the two bare `return` at :765 and :776 with `return None`; annotation `) -> Optional[Dict[str, Any]]:`
```
```python
# occurrences: 1 (verified: grep -c '    async def _on_coordination_unavailable(' …) — line :952
# INSERT above `async def _on_coordination_unavailable(`
    async def _stamp_delivery_outcome(self, schedule_id: str, outcomes: List[Dict[str, Any]]) -> None:
        """Persist delivery outcomes in ``metadata`` (FEAT-635).

        Writes ``last_callbacks``, ``last_delivery_status`` and ``last_delivery_time``.
        Never touches ``last_status``/``run_count``/``last_run``/``next_run``. Never raises.
        """
        if self._pool is None:
            self.logger.warning("Cannot stamp delivery outcome for %s: database pool is unavailable", schedule_id)
            return
        try:
            async with await self._pool.acquire() as conn:  # pylint: disable=no-member # noqa
                AgentSchedule.Meta.connection = conn
                schedule = await AgentSchedule.get(schedule_id=schedule_id)
                if not schedule.metadata:
                    schedule.metadata = {}
                # FILL IN: stored = outcomes copy with each "error" truncated to self._LAST_RESULT_MAX_CHARS;
                # set metadata["last_callbacks"]=stored, ["last_delivery_status"]=self._aggregate_delivery_status(outcomes),
                # ["last_delivery_time"]=datetime.now().isoformat(). Bounded by AC5.
                await schedule.update()
        except Exception as stamp_error:  # pragma: no cover - safety net
            self.logger.error("Failed to stamp delivery outcome for %s: %s", schedule_id, stamp_error)
```
```python
# occurrences: 1 (verified: grep -c '            await self._handle_job_success(' …) — line :849
# REPLACE `            await self._handle_job_success(` with `            outcomes = await self._handle_job_success(`
# then, still inside that try, after the call's closing paren:
            for outcome in outcomes:
                if outcome["status"] in ("failed", "partial"):
                    self.logger.warning(
                        "Delivery %s for schedule %s: %s (%s)",
                        outcome["callback"], schedule_id, outcome["status"], outcome.get("error"),
                    )
            if persist and outcomes:
                await self._stamp_delivery_outcome(schedule_id, outcomes)
```
**Why**: isolation lives inside `_handle_job_success` so the outer safety net stays a last resort. The stamp is a second, independent read-modify-write after `_update_schedule_run`. Both run in the same task, so they never race. `last_status` keeps meaning "the agent run" (spec U2).

### `packages/ai-parrot-server/tests/scheduler/test_delivery_outcomes.py` (CREATE)
```python
"""FEAT-635 M2 — the manager isolates callbacks and persists delivery outcomes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.scheduler.manager import AgentSchedulerManager


@pytest.fixture
def manager():
    """Scheduler manager without external infrastructure (pattern: test_listeners.py:13)."""
    return AgentSchedulerManager()


class _FakePoolAcquireContext:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return False


class _FakePool:
    def __init__(self):
        self.connection = MagicMock()

    async def acquire(self):
        return _FakePoolAcquireContext(self.connection)


def _cb(response=None, exc=None):
    """A fake callback instance returned by a patched build_scheduler_callback."""
    return AsyncMock(return_value=response, side_effect=exc)


async def test_handle_job_success_isolates_callbacks(manager):
    builds = [_cb(exc=RuntimeError("boom")), _cb(response={"status": "sent"})]
    with patch("parrot.scheduler.manager.build_scheduler_callback", side_effect=builds), \
         patch.object(manager, "_send_result_email", new=AsyncMock(return_value={"status": "success"})) as sr:
        outcomes = await manager._handle_job_success(
            "s1", "agent", "res", None, {"recipients": ["a@x"]},
            [{"type": "send_email_report"}, {"type": "send_notify_report"}],
        )
    assert [o["status"] for o in outcomes] == ["failed", "sent", "sent"]
    assert outcomes[2]["callback"] == "send_result"
    sr.assert_awaited_once()


async def test_handle_job_success_unknown_callback_type(manager):
    # FILL IN: real build_scheduler_callback with {"type": "nope"} → one failed outcome, no raise
    ...


async def test_send_result_failure_recorded(manager):
    # FILL IN: _send_result_email → {"status": "error", "error": "x"} → outcome send_result/failed
    ...


@pytest.mark.parametrize(
    "statuses,expected",
    [(["sent", "saved"], "ok"), (["sent", "failed"], "partial"), (["partial"], "partial"),
     (["failed", "failed"], "failed"), ([], None)],
)
def test_aggregate_delivery_status(statuses, expected):
    outcomes = [{"callback": "c", "status": s, "error": None} for s in statuses]
    assert AgentSchedulerManager._aggregate_delivery_status(outcomes) == expected


async def test_process_job_success_stamps_delivery(manager):
    # FILL IN: manager._pool = _FakePool(); schedule = SimpleNamespace(metadata={"last_status": "success"},
    # update=AsyncMock()); patch AgentSchedule.get → schedule; patch _update_schedule_run (AsyncMock) and
    # _handle_job_success → [{"callback": "c", "status": "failed", "error": "x"}];
    # await manager._process_job_success("s1", "agent", "res", None, None, [], persist=True);
    # assert last_callbacks / last_delivery_status == "failed" / last_delivery_time set; last_status still "success"
    ...


async def test_process_job_success_persist_false_skips_stamp(manager):
    # FILL IN: persist=False → _stamp_delivery_outcome (patched AsyncMock) not awaited
    ...


async def test_stamp_delivery_never_raises(manager):
    # FILL IN: _pool=_FakePool(); AgentSchedule.get raises RuntimeError → await completes without raising
    ...
```
**Why**: the fixtures are local because there is no `tests/scheduler/conftest.py`, and adding one would be shared state. Patch `parrot.scheduler.manager.build_scheduler_callback`, the name `manager.py` imports at `:56`, not the one in `functions`.

### FILL IN checklist
- [ ] `_callback_outcome`: status mapping and error text; bounded by spec §2
- [ ] `_aggregate_delivery_status`: reduction; bounded by spec §2
- [ ] `_handle_job_success`: isolated `send_result` block; bounded by AC3/AC4
- [ ] `_stamp_delivery_outcome`: metadata writes with truncation; bounded by AC5
- [ ] test stubs: five bodies; bounded by the spec §4 M2 rows

---

## Acceptance Criteria

- [ ] AC3: a raising or unknown callback never stops later callbacks or `send_result`.
- [ ] AC4: `_handle_job_success` returns one outcome per definition, plus `send_result` when configured; `success_callback` is not recorded.
- [ ] AC5: `persist=True` with outcomes writes `last_callbacks`, `last_delivery_status` and `last_delivery_time`; `last_status` is untouched.
- [ ] AC6: `persist=False` does not stamp; a stamp failure never propagates.
- [ ] AC7: every failed or partial outcome is logged at `warning` with `schedule_id` and the callback name.
- [ ] Existing scheduler tests still pass; `ruff check` is clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/scheduler/test_delivery_outcomes.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_listeners.py -q`
- `pytest packages/ai-parrot-server/tests/scheduler/test_run_now.py -q`

---

## Test Specification

See the `test_delivery_outcomes.py` block in the Implementation Blueprint. It covers the spec §4 M2 rows.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug scheduler-callback-delivery-status --feature-id FEAT-635`). Run tests with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src`.
2. Verify the Codebase Contract line numbers with `grep -n` first. FEAT-631 recently changed `manager.py`, so if an anchor moved, re-locate it by its verbatim text.
3. Set the index status to `in-progress` and commit only the index.
4. Implement from the blueprint and complete every `FILL IN`.
5. Run the Validation Commands and `ruff check`.
6. Commit only the two listed files, then run `scripts/sdd/close_task.sh TASK-4103 scheduler-callback-delivery-status verified`, fill in the Completion Note, and commit.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
