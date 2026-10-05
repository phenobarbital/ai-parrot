---
type: feature
base_branch: dev
projects: [ai-parrot-server, ai-parrot]
tags: [scheduler, notifications, callbacks, send-email-report, delivery-status]
---

# Feature Specification: Scheduler callback delivery status

**Feature ID**: FEAT-635
**Date**: 2026-10-05
**Author**: Jesus Lara (spec drafted by Claude)
**Status**: approved
**Target version**: ai-parrot-server 0.28.x
**Source**: GitHub issue [phenobarbital/ai-parrot#1574](https://github.com/phenobarbital/ai-parrot/issues/1574) · proposal `sdd/proposals/gh-1574-scheduler-callback-delivery-status.proposal.md` (research audit `sdd/state/GH-1574/`)

---

## 1. Motivation & Business Requirements

### Problem Statement

`NotificationMixin.send_*` methods never raise. They report a provider failure as `{"status": "error", ...}`, and `NotificationMixin.notification_succeeded()` exists to check for it. The scheduler never calls that check:

- `send_email_report` and `send_notify_report` return `status: "sent"` unconditionally. `saving_data` buries a failed email under `response["email"]` while still reporting `status: "saved"`.
- `AgentSchedulerManager._handle_job_success` discards each callback's return value. Callbacks are not isolated, so one that raises skips every later callback and also skips `send_result`. `_send_result_email` ignores the notifier status.
- `_process_job_success` stamps `last_status="success"` before callbacks run and only logs callback errors. Nothing about delivery is ever saved.

As a result, direct callers (such as the external reportbuilder package) and anyone looking at the schedule row cannot tell that a delivery failed.

### Goals
- G1: Every delivery callback reports `"sent"` only when `notification_succeeded()` confirms the send. Otherwise it returns `status: "failed"` with the provider error, and it never raises because of a provider failure.
- G2: `saving_data` reports email failure at the top level.
- G3: The manager runs each callback, and `send_result`, independently. A failure in one never prevents the others.
- G4: The manager collects one outcome per callback (and for `send_result`) and saves them on the schedule row as `metadata.last_callbacks`, `metadata.last_delivery_status` and `metadata.last_delivery_time`, without changing `last_status`.
- G5: Each delivery failure is logged at `warning` level with `schedule_id` and the callback name.

### Non-Goals (explicitly out of scope)
- Changing `NotificationMixin` or the never-raise convention of `send_*` (the fix belongs in the callers).
- Retrying failed deliveries.
- Showing delivery status in handlers or the admin UI (possible follow-up).
- async-notify version pins. The venv drift mentioned in the issue is already resolved (venv 2.0.0 = `uv.lock`).
- A DDL change. `AgentSchedule.metadata` is JSONB.

---

## 2. Architectural Design

### Overview

**Callbacks (M1).** `BaseSchedulerCallback` gains one helper, `_delivery_result()`. It turns a `send_*` response into the callback's return dict, using `notification_succeeded()` to decide between `status: "sent"` and `status: "failed"`. The failure dict carries `error` (the provider's `error` field, or a generic message when it has none) and the original `response`.
- `SendEmailReportCallback` and `SendNotifyReportCallback` return `_delivery_result(...)`.
- `SaveDataCallback` keeps `status: "saved"` when there is no email, or when the email succeeded. When an email is configured and fails, it returns `status: "partial"`, with `email_status: "failed"` and `error`. Whenever an email is configured, `email_status` is present (`"sent" | "failed"`).
- Provider failures never raise. Configuration errors that raise today keep raising: missing recipients, missing tabular data, missing weasyprint.

**Manager (M2).** `_handle_job_success` returns a `list[dict]` of outcomes, one per configured callback plus one for `send_result` when it is configured. `success_callback`, the user's own Python callable, is not a delivery: it keeps its current behaviour and is not recorded.

Each entry is built by a static `_callback_outcome()` helper:

```
{"callback": <name>, "status": "sent"|"saved"|"partial"|"failed", "error": str|None}
```

- A callback that raises is caught. Its outcome is `status: "failed"` with `error=str(exc)`, and the loop continues.
- `build_scheduler_callback` errors are caught the same way. The name comes from `definition.get("type") or definition.get("name")`.
- `_send_result_email` returns the notifier's dict, or `None` for its early-return paths (invalid config, no recipients). A `None` is recorded as `failed`, with the reason as `error`.

`_aggregate_delivery_status(outcomes)` reduces the list:
- `"ok"` when every entry is `sent` or `saved`;
- `"failed"` when every entry is `failed`;
- `"partial"` otherwise, including any `partial` entry;
- `None` for an empty list.

`_process_job_success`, after `_handle_job_success` and only when `persist=True` and `outcomes` is non-empty, calls a new `_stamp_delivery_outcome(schedule_id, outcomes)`. That method follows the `_on_coordination_unavailable` pattern: its own pool acquire, `AgentSchedule.get`, a mutation of `metadata` only, `update()`, and it never raises. It writes:

- `last_callbacks` — the outcome list, with `error` truncated to `_LAST_RESULT_MAX_CHARS`
- `last_delivery_status`
- `last_delivery_time` — ISO timestamp

It never touches `last_status`, `run_count`, `last_run` or `next_run`. With no pool, it logs a warning and returns. Each failed or partial outcome is logged at `warning` level.

### Component Diagram
```
job_success ─→ _process_job_success
                 ├─ _update_schedule_run(success=True)        (unchanged; last_status = run status)
                 ├─ outcomes = _handle_job_success(...)
                 │     ├─ success_callback(result)             (unchanged, not recorded)
                 │     ├─ for each definition: try build+call → _callback_outcome()
                 │     │     └─ callback.run → BaseSchedulerCallback._delivery_result(response)
                 │     │                         └─ NotificationMixin.notification_succeeded()
                 │     └─ send_result: _send_result_email → notifier dict → _callback_outcome()
                 └─ persist and outcomes → _stamp_delivery_outcome(schedule_id, outcomes)
                                              └─ metadata.last_callbacks / last_delivery_status / last_delivery_time
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `NotificationMixin.notification_succeeded` | uses | staticmethod; the only success check (no re-implementation) |
| `BaseSchedulerCallback` | extends | adds `_delivery_result` |
| `AgentSchedulerManager._handle_job_success` | modifies | returns `list[dict]`; isolates each callback |
| `AgentSchedulerManager._send_result_email` | modifies | returns `Optional[Dict[str, Any]]` |
| `AgentSchedulerManager._process_job_success` | modifies | calls `_stamp_delivery_outcome` |
| `AgentSchedule.metadata` | uses | three new JSONB keys, no DDL |

### Data Models
Plain dicts (they are stored as JSONB and returned to direct callers), no new Pydantic model:
```python
# Callback return (M1)
{"status": "sent" | "failed", "provider": str, "attachments": list[str], "response": dict | None, "error": str | None}
# SaveDataCallback (M1)
{"status": "saved" | "partial", "path": str, "rows": int, "email": dict, "email_status": "sent" | "failed", "error": str | None}
# Outcome entry (M2) — element of metadata.last_callbacks
{"callback": str, "status": "sent" | "saved" | "partial" | "failed", "error": str | None}
```

### New Public Interfaces
The only new public-facing contract is the callbacks' return dicts above. Everything else is a private method.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Callback delivery results | yes | `_delivery_result` signature + return shapes fixed in §2 Data Models; `notification_succeeded` is the only predicate | — |
| M2: Manager outcome collection + stamp | yes | method names/signatures in skeleton; aggregation table in §2; stamp pattern = `_on_coordination_unavailable` | — |

### Module 1: Callback delivery results
- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py`
- **Responsibility**: Callbacks return the real delivery status.
- **Depends on**: existing `NotificationMixin.notification_succeeded`
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py
  class BaseSchedulerCallback(NotificationMixin):  # verified: functions/__init__.py:16
      def _delivery_result(
          self,
          response: Optional[Dict[str, Any]],
          *,
          provider: str,
          attachments: Optional[List[Path]] = None,
      ) -> Dict[str, Any]:
          """Turn a ``send_*`` response into a callback result.

          Returns ``{"status": "sent", ...}`` only when
          ``self.notification_succeeded(response)`` is true; otherwise
          ``{"status": "failed", "error": <response['error'] or generic>, ...}``.
          Always includes ``provider``, ``attachments`` (as str) and ``response``.
          Never raises.
          """

  class SendEmailReportCallback(BaseSchedulerCallback):  # verified: :68
      async def run(...) -> Dict[str, Any]:  # return line verified: :92
          """…returns self._delivery_result(response, provider="email", attachments=attachments)."""

  class SaveDataCallback(BaseSchedulerCallback):  # verified: :130
      async def run(...) -> Dict[str, Any]:  # email branch verified: :145-153
          """status 'saved'; when email_to is set adds email_status ('sent'|'failed');
          failed email → status 'partial' + error."""

  class SendNotifyReportCallback(BaseSchedulerCallback):  # verified: :168
      async def run(...) -> Dict[str, Any]:  # return line verified: :192
          """…returns self._delivery_result(response, provider=provider, attachments=attachments)."""
  ```

### Module 2: Manager outcome collection and persistence
- **Path**: `packages/ai-parrot-server/src/parrot/scheduler/manager.py`
- **Responsibility**: Run each callback independently, collect outcomes, save the delivery status.
- **Depends on**: M1's return-dict contract (`status` key). It does not import any M1 symbol.
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot-server/src/parrot/scheduler/manager.py
  class AgentSchedulerManager:
      async def _handle_job_success(  # verified: manager.py:732
          self, schedule_id: str, agent_name: str, result: Any,
          success_callback: Optional[Callable], send_result: Optional[Dict[str, Any]],
          callbacks: Optional[List[Dict[str, Any]]] = None,
      ) -> List[Dict[str, Any]]:
          """Run success_callback (unchanged), then each callback definition and send_result,
          each in its own try. Returns one outcome per callback definition (+ 'send_result'
          when configured). Never raises for a callback/send failure."""

      async def _send_result_email(  # verified: manager.py:755
          self, schedule_id: str, agent_name: str, result: Any, send_result: Dict[str, Any],
      ) -> Optional[Dict[str, Any]]:
          """Return the notifier response dict (verified send site: manager.py:810);
          None on the early-return paths (invalid config / missing recipients)."""

      @staticmethod
      def _callback_outcome(name: str, response: Any = None, error: Optional[BaseException | str] = None) -> Dict[str, Any]:
          """Build {'callback', 'status', 'error'}. A raised error → 'failed'. A dict response →
          its 'status' ('sent'|'saved'|'partial'|'failed'), normalised so a NotificationMixin
          'success' → 'sent' and 'error' → 'failed'. None/unknown → 'failed'."""

      @staticmethod
      def _aggregate_delivery_status(outcomes: List[Dict[str, Any]]) -> Optional[str]:
          """'ok' | 'partial' | 'failed' per §2; None when outcomes is empty."""

      async def _stamp_delivery_outcome(self, schedule_id: str, outcomes: List[Dict[str, Any]]) -> None:
          """Write metadata.last_callbacks / last_delivery_status / last_delivery_time.
          Pattern: _on_coordination_unavailable (manager.py:952). Never raises; never touches
          last_status/run_count/last_run/next_run."""

      async def _process_job_success(...)  # verified: manager.py:819; call site :849
          """outcomes = await self._handle_job_success(...); if persist and outcomes:
          await self._stamp_delivery_outcome(schedule_id, outcomes)."""
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_send_email_report_failed_status` | M1 | patched `send_email` returns `{"status": "error", "error": "smtp down"}`; result `status == "failed"`, `error == "smtp down"` |
| `test_send_email_report_sent_status` | M1 | patched `send_email` returns `{"status": "success"}`; result `status == "sent"` |
| `test_send_notify_report_failed_status` | M1 | same for `send_notification` |
| `test_saving_data_email_failure_is_partial` | M1 | CSV written; email `{"status": "error"}`; `status == "partial"`, `email_status == "failed"` |
| `test_saving_data_without_email_is_saved` | M1 | no `email_to`; `status == "saved"`, no `email_status` key |
| `test_delivery_result_none_response_failed` | M1 | `_delivery_result(None, provider="email")` → `failed` with a generic error |
| `test_handle_job_success_isolates_callbacks` | M2 | first callback raises, second returns sent, send_result configured → all three outcomes; second callback and send_result ran |
| `test_handle_job_success_unknown_callback_type` | M2 | `{"type": "nope"}` → `failed` outcome, loop continues |
| `test_send_result_failure_recorded` | M2 | notifier returns `{"status": "error"}` → outcome `send_result` / `failed` |
| `test_aggregate_delivery_status` | M2 | parametrised: all sent → ok; mixed → partial; all failed → failed; `[]` → None |
| `test_process_job_success_stamps_delivery` | M2 | `_FakePool` + patched `AgentSchedule.get`: metadata gets `last_callbacks`, `last_delivery_status`, `last_delivery_time`; `last_status` unchanged by the stamp |
| `test_process_job_success_persist_false_skips_stamp` | M2 | `persist=False` → `_stamp_delivery_outcome` not awaited |
| `test_stamp_delivery_never_raises` | M2 | `AgentSchedule.get` raises → no exception propagates |

Location:
- M1 → `packages/ai-parrot-server/tests/scheduler/test_callback_delivery.py` (new)
- M2 → `packages/ai-parrot-server/tests/scheduler/test_delivery_outcomes.py` (new; reuse the `manager` fixture / `_FakePool` pattern from `test_listeners.py:13-71`)

### Integration Tests
None. No live provider is needed, and every send is mocked.

### Test Data / Fixtures
```python
ERROR = {"status": "error", "provider": "email", "error": "smtp down"}
SUCCESS = {"status": "success", "provider": "email"}
```

---

## 5. Acceptance Criteria

- [ ] AC1: `send_email_report` and `send_notify_report` return `status: "sent"` iff `notification_succeeded(response)`; otherwise `status: "failed"` with `error`. Neither raises on a provider failure.
- [ ] AC2: `saving_data` with a failed email returns `status: "partial"` and `email_status: "failed"`. With a successful email it returns `status: "saved"`, `email_status: "sent"`.
- [ ] AC3: a raising or unknown callback does not stop later callbacks or `send_result`.
- [ ] AC4: `_handle_job_success` returns one outcome per callback definition, plus `send_result` when configured. `success_callback` is not recorded.
- [ ] AC5: with `persist=True` and non-empty outcomes, the row's `metadata` gains `last_callbacks`, `last_delivery_status` (`ok|partial|failed`) and `last_delivery_time`. `last_status` keeps the agent-run value (U2).
- [ ] AC6: `persist=False` performs no delivery stamp, and a stamp failure never propagates out of `_process_job_success`.
- [ ] AC7: every failed or partial outcome is logged at `warning` level with `schedule_id` and the callback name.
- [ ] AC8: no change to `NotificationMixin`, and no DDL change.
- [ ] AC9: the new tests and the existing `packages/ai-parrot-server/tests/scheduler/` and `packages/ai-parrot/tests/scheduler/test_scheduler_callbacks.py` pass; `ruff check` is clean on the touched files.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.scheduler.functions import build_scheduler_callback, list_supported_callbacks  # verified: packages/ai-parrot/tests/scheduler/test_scheduler_callbacks.py:1
from parrot.notifications import NotificationMixin  # verified: functions/__init__.py:13 (relative `from ...notifications import NotificationMixin`)
# manager.py already imports: build_scheduler_callback (:56), NotificationMixin (:54), AgentSchedule (:43), datetime (:15)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/notifications/__init__.py
class NotificationMixin:
    @staticmethod
    def notification_succeeded(result: Optional[Dict[str, Any]]) -> bool:  # line 303-328 — True iff result['status'] == 'success'
    @classmethod
    def _notification_error(cls, exc, provider=None) -> Dict[str, Any]:  # line 325 — {'status': 'error', 'error': ..., 'provider': ...}
    async def send_email(self, message=None, recipients=None, subject=None, report=None, template=None, *, with_attachments=True, provider_options=None, **kwargs) -> Dict[str, Any]:  # line 1521

# packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py
class BaseSchedulerCallback(NotificationMixin):  # line 16
    def __init__(self, config: Optional[Dict[str, Any]] = None, logger=None) -> None:  # line 22
    def process_output(self, result: Any) -> Dict[str, Any]:  # line 33
    async def __call__(self, result, *, schedule_id: str, agent_name: str, **kwargs) -> Dict[str, Any]:  # line 64
class SendEmailReportCallback(BaseSchedulerCallback):  # line 68, callback_name = "send_email_report"
class SaveDataCallback(BaseSchedulerCallback):  # line 130, callback_name = "saving_data"
class SendNotifyReportCallback(BaseSchedulerCallback):  # line 168, callback_name = "send_notify_report"
def build_scheduler_callback(definition: Dict[str, Any], logger=None) -> BaseSchedulerCallback:  # line 210 — raises ValueError on unknown type

# packages/ai-parrot-server/src/parrot/scheduler/manager.py
class _SchedulerNotification(NotificationMixin):  # line 342
class AgentSchedulerManager:  # line 349
    async def _handle_job_success(self, schedule_id, agent_name, result, success_callback, send_result, callbacks=None) -> None:  # line 732
    async def _send_result_email(self, schedule_id, agent_name, result, send_result) -> None:  # line 755
    async def _process_job_success(self, schedule_id, agent_name, result, success_callback, send_result, callbacks=None, *, persist: bool = True) -> None:  # line 819
    _LAST_RESULT_MAX_CHARS  # line 889
    async def _update_schedule_run(self, schedule_id, success=True, error=None, result=None):  # line 891
    async def _on_coordination_unavailable(self, job_id: str, exc: BaseException) -> None:  # line 952 — stamp pattern to copy
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_delivery_result` | `NotificationMixin.notification_succeeded` | `self.notification_succeeded(response)` | `notifications/__init__.py:303` |
| `_handle_job_success` outcomes | `callback(result, schedule_id=..., agent_name=...)` | return value | `manager.py:750` |
| `_send_result_email` return | `notifier.send_email(...)` | return value | `manager.py:810` |
| `_stamp_delivery_outcome` | `_process_job_success` | call after `_handle_job_success` | `manager.py:849` |

### Does NOT Exist (Anti-Hallucination)
- ~~`SchedulerCallbackDeliveryError`~~ — no such exception, and none is created (U1: return, don't raise)
- ~~`AgentSchedule.delivery_status` / `last_callbacks` column~~ — no columns; these are `metadata` keys only
- ~~`NotificationMixin.notification_failed()`~~ — only `notification_succeeded` exists
- ~~`parrot.scheduler.callbacks`~~ — callbacks live in `parrot.scheduler.functions`
- ~~any existing behavioural test of callback status~~ — `test_scheduler_callbacks.py` covers only the registry

### Edit Sites (Blueprint Anchors)

Verified against: `ab99a8523`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py` | MODIFY | `    def process_output(self, result: Any) -> Dict[str, Any]:` (insert `_delivery_result` before/after) | `:33` | 1 |
| same | MODIFY | `        return {"status": "sent", "provider": "email", "attachments": [str(p) for p in attachments], "response": response}` | `:92` | 1 |
| same | MODIFY | `            response["email"] = email_response` | `:153` | 1 |
| same | MODIFY | `        return {"status": "sent", "provider": provider, "attachments": [str(p) for p in attachments], "response": response}` | `:192` | 1 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py` | MODIFY | `    async def _handle_job_success(` | `:732` | 1 |
| same | MODIFY | `            await callback(result, schedule_id=schedule_id, agent_name=agent_name)` | `:750` | 1 |
| same | MODIFY | `    async def _send_result_email(` | `:755` | 1 |
| same | MODIFY | `        await notifier.send_email(` | `:810` | 1 |
| same | MODIFY | `            await self._handle_job_success(` | `:849` | 1 |
| same | MODIFY | `    async def _on_coordination_unavailable(` (add `_stamp_delivery_outcome` near it) | `:952` | 1 |
| `packages/ai-parrot-server/tests/scheduler/test_callback_delivery.py` | CREATE | — | — | — |
| `packages/ai-parrot-server/tests/scheduler/test_delivery_outcomes.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Use `self.notification_succeeded(...)` / `NotificationMixin.notification_succeeded(...)`. Never compare `status == "success"` inline.
- Copy the DB stamp from `_on_coordination_unavailable` (`manager.py:952-975`): pool-None guard, `async with await self._pool.acquire()`, `AgentSchedule.Meta.connection = conn`, mutate `metadata`, `await schedule.update()`, and a broad `except` that logs.
- Keep the existing `except Exception` safety net in `_process_job_success`. Per-callback isolation is added inside `_handle_job_success`, not by removing the outer guard.
- Logging goes through `self.logger`, with `warning` for delivery failures. No `print`.

### Known Risks / Gotchas
- **Ordering:** `_update_schedule_run` and `_stamp_delivery_outcome` are two separate read-modify-writes on the same row. They run one after the other inside one task, so they don't race each other. The stamp must re-`get` the row, never reuse a stale object, so it doesn't overwrite `last_result`.
- **Return-type change:** `_handle_job_success` changes from `-> None` to `-> List[...]`. Check its only caller with `grep -n "_handle_job_success" packages/ai-parrot-server/src`, and patch existing tests that mock it with `AsyncMock()` if they assert the return value.
- **Behaviour change for direct callers:** a callback that used to return `"sent"` on failure now returns `"failed"`. That is the fix, and it is in the PR notes.
- **The `error` field can be long** (provider tracebacks). Truncate it to `_LAST_RESULT_MAX_CHARS` before saving.
- **Run-now / decorator tasks** use `persist=False`. They must still collect outcomes, which are useful in logs, but they must not stamp.

### External Dependencies
None.

---

## 8. Open Questions

- [x] How a callback fails — *Resolved in proposal (U1)*: return `status: "failed"` (no raise), matching the NotificationMixin never-raise convention.
- [x] Persistence — *Resolved in proposal (U2)*: separate keys `metadata.last_delivery_status` (`ok|partial|failed`) plus `metadata.last_callbacks[]`. `last_status` stays the agent-run status.
- [x] Isolation — *Resolved in proposal (U3)*: continue; each callback is isolated, and failures are recorded but not fatal to siblings.
- [x] `SaveDataCallback` top-level status when the email fails — *Decided at spec time, confirmed by user at review (2026-10-05)*: `"partial"` + `email_status: "failed"`, so the manager's `status`-only classification sees the failure without special-casing `email_status`.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (exploration doc status is `review`, not `accepted`) · Transcript: none

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation:** one feature worktree, `feat-FEAT-635-scheduler-callback-delivery-status`, based on `origin/dev`. Each task gets its own sub-worktree from the `sdd-coder` engine.
- **Module dependency graph:** M1 and M2 share no edge. M2 relies only on the `status` key convention, not on any M1 symbol, so they can run concurrently.
- **Shared files:** none. M1 touches only `functions/__init__.py` and its new test file; M2 touches only `manager.py` and its new test file.
- **Exclusive resources:** none (no lockfile, migration or build step).
- **Cross-feature dependencies:** FEAT-631 (scheduler-multiworker-correctness) recently changed `manager.py`. It is already on `dev`; rebase on the latest `origin/dev` before starting.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-05 | Jesus Lara / Claude | Initial draft from proposal GH-1574 |
| 0.2 | 2026-10-05 | Jesus Lara | Review: confirmed U1–U3 and the `saving_data` "partial" decision; status → approved |
