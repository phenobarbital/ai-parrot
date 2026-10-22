# TASK-4102: Callback delivery results

**Feature**: FEAT-635 — Scheduler callback delivery status
**Spec**: `sdd/specs/scheduler-callback-delivery-status.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 1** (GitHub issue #1574). Today `send_email_report` and `send_notify_report` return `status: "sent"` even when the provider failed. `NotificationMixin.send_*` never raises; it returns `{"status": "error", ...}`. `saving_data` hides a failed email under `response["email"]`. This task makes the callbacks report the real status, using the existing `NotificationMixin.notification_succeeded()`.

---

## Scope

- Add `BaseSchedulerCallback._delivery_result(response, *, provider, attachments=None) -> Dict[str, Any]`.
- Make `SendEmailReportCallback.run` and `SendNotifyReportCallback.run` return `self._delivery_result(...)`.
- Make `SaveDataCallback.run`, when `email_to` is configured, add `email_status` (`"sent"`/`"failed"`). A failed email makes the top-level status `"partial"` and adds `error`.
- Write unit tests in a new `test_callback_delivery.py`.

**NOT in scope**:
- `manager.py`: outcome collection and persistence are TASK-4103.
- `NotificationMixin`: no change.
- `CreateFileCallback`: it sends nothing.
- Changing which configuration errors raise (missing recipients, missing data, missing weasyprint keep raising).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py` | MODIFY | `_delivery_result` + three `run` return paths |
| `packages/ai-parrot-server/tests/scheduler/test_callback_delivery.py` | CREATE | Unit tests for M1 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in functions/__init__.py — add nothing new:
from typing import Any, Dict, List, Optional, Type  # verified: functions/__init__.py:7
from pathlib import Path                            # verified: functions/__init__.py:6
from ...notifications import NotificationMixin      # verified: functions/__init__.py:13
# Tests:
from parrot.scheduler.functions import build_scheduler_callback  # verified: packages/ai-parrot/tests/scheduler/test_scheduler_callbacks.py:1
from parrot.scheduler.functions import SendEmailReportCallback, SaveDataCallback, SendNotifyReportCallback  # verified: module-level classes, functions/__init__.py:68,130,168
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/notifications/__init__.py
class NotificationMixin:
    @staticmethod
    def notification_succeeded(result: Optional[Dict[str, Any]]) -> bool:  # line 303 — True iff result["status"] == "success"; None → False
    @classmethod
    def _notification_error(cls, exc, provider=None) -> Dict[str, Any]:  # line 325 — failure payload {"status": "error", "error": ..., "provider": ...}
    async def send_email(self, message=None, recipients=None, subject=None, report=None, template=None, *, with_attachments=True, provider_options=None, **kwargs) -> Dict[str, Any]:  # line 1521

# packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py
class BaseSchedulerCallback(NotificationMixin):  # line 16
    def __init__(self, config: Optional[Dict[str, Any]] = None, logger=None) -> None:  # line 22
    def process_output(self, result: Any) -> Dict[str, Any]:  # line 33
class SendEmailReportCallback(BaseSchedulerCallback):  # line 68
    async def run(self, result, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]:  # line 72; send at :85; return at :92
class SaveDataCallback(BaseSchedulerCallback):  # line 130
    async def run(...):  # line 134; email branch :145-153; `return response` :154
class SendNotifyReportCallback(BaseSchedulerCallback):  # line 168
    async def run(...):  # line 172; send_notification at :185; return at :192
```

### Does NOT Exist
- ~~`SchedulerCallbackDeliveryError`~~: do not create an exception; failures are returned (spec U1).
- ~~`NotificationMixin.notification_failed()`~~: only `notification_succeeded` exists.
- ~~`parrot.scheduler.callbacks`~~: the module is `parrot.scheduler.functions`.
- ~~`_delivery_result` already present~~: it is new in this task.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/scheduler/test_callback_delivery.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/notifications/__init__.py#NotificationMixin.notification_succeeded",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py#BaseSchedulerCallback",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py#SendEmailReportCallback.run",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py#SaveDataCallback.run",
    "sym:packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py#SendNotifyReportCallback.run"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Use `self.notification_succeeded(response)`. Never compare `status == "success"` inline, because the predicate is the single source of truth (spec §7).
- Never raise on a provider failure (spec U1, AC1).
- Keep the existing keys (`provider`, `attachments`, `response`) so direct callers keep working. Only `status` changes, and `error` is added.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_delivery_result` to `BaseSchedulerCallback`, right after `process_output`. *Why*: all three callbacks share one result shape (spec §2 Data Models).
2. Replace the return at `:92` and the return at `:192` with `_delivery_result(...)`. *Why*: AC1.
3. Change the `SaveDataCallback` email branch at `:153`. *Why*: AC2, and the decision recorded in spec §8 (`"partial"`).
4. Write the tests, then run the Validation Commands.

### `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    def process_output(self, result: Any) -> Dict\[str, Any\]:' …/functions/__init__.py)
# INSERT as a new method of BaseSchedulerCallback, after process_output (ends at :59), before `async def run` (:61)
    def _delivery_result(
        self,
        response: Optional[Dict[str, Any]],
        *,
        provider: str,
        attachments: Optional[List[Path]] = None,
    ) -> Dict[str, Any]:
        """Turn a ``send_*`` response into a callback result.

        ``NotificationMixin.send_*`` never raises: a provider failure comes back
        as ``{"status": "error", ...}``. This reports ``"sent"`` only when
        :meth:`notification_succeeded` confirms the send, and ``"failed"``
        (with ``error``) otherwise. It never raises.

        Args:
            response: The dict returned by a ``send_*`` method, or ``None``.
            provider: Provider label for the result (``"email"``, ``"telegram"``, ...).
            attachments: Files that were attached, reported as strings.

        Returns:
            ``{"status", "provider", "attachments", "response", "error"}``.
        """
        sent = self.notification_succeeded(response)
        error = None
        if not sent:
            # FILL IN: error text — use response.get("error") when response is a dict with
            # a truthy "error"; otherwise a generic f"{provider} delivery failed". Bounded by AC1.
            ...
        return {
            "status": "sent" if sent else "failed",
            "provider": provider,
            "attachments": [str(p) for p in attachments or []],
            "response": response,
            "error": error,
        }
```
```python
# occurrences: 1 (verified: grep -c 'return {"status": "sent", "provider": "email"' …) — line :92
# REPLACE
        return self._delivery_result(response, provider="email", attachments=attachments)
```
```python
# occurrences: 1 (verified: grep -c 'return {"status": "sent", "provider": provider' …) — line :192
# REPLACE
        return self._delivery_result(response, provider=provider, attachments=attachments)
```
```python
# occurrences: 1 (verified: grep -c '            response\["email"\] = email_response' …) — line :153
# AFTER `response["email"] = email_response`, inside the `if self.config.get("email_to"):` branch
            if self.notification_succeeded(email_response):
                response["email_status"] = "sent"
            else:
                response["email_status"] = "failed"
                response["status"] = "partial"
                # FILL IN: response["error"] — email_response.get("error") when present, else
                # "email delivery failed"; bounded by AC2 (spec §8: 'partial' + email_status)
```
**Why**: the helper keeps the old keys, so existing callers that read `provider`, `attachments` or `response` still work. Only `status` now reflects reality. `saving_data` reports `"partial"` so that TASK-4103's manager can classify the outcome from `status` alone (spec §8).

### `packages/ai-parrot-server/tests/scheduler/test_callback_delivery.py` (CREATE)
```python
"""FEAT-635 M1 — scheduler callbacks report the real delivery status."""

from unittest.mock import AsyncMock, patch

import pytest

from parrot.scheduler.functions import (
    SaveDataCallback,
    SendEmailReportCallback,
    SendNotifyReportCallback,
)

ERROR = {"status": "error", "provider": "email", "error": "smtp down"}
SUCCESS = {"status": "success", "provider": "email"}


async def test_send_email_report_failed_status():
    cb = SendEmailReportCallback(config={"recipients": ["a@example.com"]})
    with patch.object(SendEmailReportCallback, "send_email", new=AsyncMock(return_value=ERROR)):
        out = await cb.run("report body", schedule_id="s1", agent_name="agent")
    assert out["status"] == "failed"
    assert out["error"] == "smtp down"


async def test_send_email_report_sent_status():
    # FILL IN: same as above with SUCCESS → status "sent", error None
    ...


async def test_send_notify_report_failed_status():
    # FILL IN: patch SendNotifyReportCallback.send_notification → ERROR; config {"recipients": ["x"]};
    # assert status "failed"
    ...


async def test_saving_data_email_failure_is_partial(tmp_path):
    # FILL IN: result object with .data=[{"a": 1}] (e.g. types.SimpleNamespace(data=..., response="x"));
    # config {"output_dir": str(tmp_path), "email_to": ["a@example.com"]}; patch send_email → ERROR;
    # assert status "partial", email_status "failed", CSV exists
    ...


async def test_saving_data_without_email_is_saved(tmp_path):
    # FILL IN: no email_to → status "saved", "email_status" not in result
    ...


def test_delivery_result_none_response_failed():
    out = SendEmailReportCallback(config={})._delivery_result(None, provider="email")
    assert out["status"] == "failed"
    assert out["error"]
```
**Why**: the tests mock `send_*` at the class level, so no provider or network is touched. `asyncio_mode = "auto"` is set in `packages/ai-parrot-server/pyproject.toml:123`, so no `@pytest.mark.asyncio` is needed.

### FILL IN checklist
- [ ] `_delivery_result`: error text derivation; bounded by AC1
- [ ] `SaveDataCallback.run`: `response["error"]` on a failed email; bounded by AC2
- [ ] test bodies: the four stubs; bounded by the spec §4 M1 rows

---

## Acceptance Criteria

- [ ] AC1: `send_email_report` and `send_notify_report` return `"sent"` iff `notification_succeeded(response)`, else `"failed"` + `error`. Neither raises on a provider failure.
- [ ] AC2: `saving_data` with a failed email returns `status: "partial"` + `email_status: "failed"`. With a successful email it returns `"saved"` + `email_status: "sent"`. With no email, it has no `email_status`.
- [ ] Existing registry tests still pass.
- [ ] `ruff check packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py packages/ai-parrot-server/tests/scheduler/test_callback_delivery.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/scheduler/test_callback_delivery.py -q`
- `pytest packages/ai-parrot/tests/scheduler/test_scheduler_callbacks.py -q`

---

## Test Specification

See the `test_callback_delivery.py` block in the Implementation Blueprint. It covers the spec §4 rows `test_send_email_report_failed_status`, `test_send_email_report_sent_status`, `test_send_notify_report_failed_status`, `test_saving_data_email_failure_is_partial`, `test_saving_data_without_email_is_saved` and `test_delivery_result_none_response_failed`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug scheduler-callback-delivery-status --feature-id FEAT-635`). Run tests with `PYTHONPATH=packages/ai-parrot-server/src:packages/ai-parrot/src`.
2. Read the spec, then verify the Codebase Contract with `grep -n` before editing.
3. Set the index status to `in-progress` and commit only the index.
4. Implement from the blueprint and complete every `FILL IN`.
5. Run the Validation Commands and `ruff check`.
6. Commit only the two listed files, then run `scripts/sdd/close_task.sh TASK-4102 scheduler-callback-delivery-status verified`, fill in the Completion Note, and commit.

---

## Completion Note

Implemented by codex seat via coder_run_chunk; merged by engine, reviewed by orchestrator against spec (diff matches §2). Scheduler tests pass (237 passed). Merge-tier run reported 6 pre-existing errors in packages/ai-parrot-server/tests/studio/test_integration.py (byok.load_master_keys missing), a file not touched by this feature. Delivery metrics/feedback: no corrections needed.

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
