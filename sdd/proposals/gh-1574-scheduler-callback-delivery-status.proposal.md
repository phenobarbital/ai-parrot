---
id: GH-1574  # provisional; /sdd-spec reserves the real FEAT-<NNN> via reserve_ids.py
title: "Scheduler delivery callbacks: report real send status, isolate each callback, persist delivery outcomes"
slug: gh-1574-scheduler-callback-delivery-status
type: feature
mode: investigation
status: review
source:
  kind: github_issue
  github_issue: phenobarbital/ai-parrot#1574
  url: https://github.com/phenobarbital/ai-parrot/issues/1574
  fetched_at: 2026-10-05
  summary_oneline: "notifications: send_email_report reports success when sending failed"
overall_confidence: high
base_branch: dev
projects: [ai-parrot-server, ai-parrot]
tags: [scheduler, notifications, callbacks, send-email-report, delivery-status]
research_state: sdd/state/GH-1574/
created: 2026-10-05
updated: 2026-10-05
---

# GH-1574: Scheduler delivery callbacks report real send status

> **Mode**: investigation
> **Confidence**: high. Every claim cites the source directly, the fix reuses an existing predicate, and all three design questions were answered by the user.
> **Source**: [phenobarbital/ai-parrot#1574](https://github.com/phenobarbital/ai-parrot/issues/1574)
> **Audit**: [`sdd/state/GH-1574/`](../state/GH-1574/)

---

## 0. Origin

GitHub issue #1574, found while integrating the scheduler into an external package (reportbuilder):

> `NotificationMixin.send_email` and `send_teams_card` never raise; they return a status dict. `send_email_report` (`scheduler/functions`) ignores that status and reports "sent" even when the provider failed. Callback results and errors are also only logged or discarded (`manager.py`), so callers can't tell a delivery failed.
>
> **Suggested fix:** check `notification_succeeded` (or equivalent) and propagate failure; persist callback outcomes.
>
> Related: the repo `.venv` had async-notify 1.6.0 while `uv.lock` pins 2.0.0.

## 1. Synthesis Summary

The issue is accurate, and the problem is wider than the one callback it names. The repo already has the right building block: `NotificationMixin.notification_succeeded()`. No delivery callback calls it, and neither does the scheduler manager. As a result:

1. `send_email_report` and `send_notify_report` always return `status: "sent"`. `saving_data` hides a failed email under `response["email"]` [F001].
2. The manager discards each callback's return value. Callbacks are not isolated, so one that raises skips the rest and also skips `send_result`. `send_result`'s own email status is ignored too [F003].
3. The schedule row is stamped `last_status="success"` **before** callbacks run, and nothing about delivery is ever saved [F003, F004].

The fix touches two files in `ai-parrot-server`, adds tests, and needs no DDL change: the outcomes go into the `metadata` JSONB field [F004].

The async-notify note in the issue is environment drift that has since been fixed. The venv now has 2.0.0, which matches `uv.lock`, so no code change is needed [F005].

## 2. Codebase Findings

### 2.1 Localization

| Path / symbol | Lines | Role | Evidence |
|---|---|---|---|
| `packages/ai-parrot-server/src/parrot/scheduler/functions/__init__.py::SendEmailReportCallback.run` | 72-92 | returns `"sent"` whatever the result | F001 |
| `…/scheduler/functions/__init__.py::SendNotifyReportCallback.run` | 172-192 | same pattern | F001 |
| `…/scheduler/functions/__init__.py::SaveDataCallback.run` | 134-154 | email failure buried under `"saved"` | F001 |
| `…/scheduler/functions/__init__.py::BaseSchedulerCallback` | 16-65 | inherits `NotificationMixin`, so the predicate is already available | F001 |
| `packages/ai-parrot/src/parrot/notifications/__init__.py::NotificationMixin.notification_succeeded` | 303-328 | existing success predicate (no change) | F002 |
| `packages/ai-parrot-server/src/parrot/scheduler/manager.py::_handle_job_success` | 733-754 | discards results, no per-callback isolation | F003 |
| `…/scheduler/manager.py::_send_result_email` | 756-818 | ignores the notifier status | F003 |
| `…/scheduler/manager.py::_process_job_success` | 820-865 | stamps success before callbacks; errors only logged | F003 |
| `…/scheduler/manager.py::_update_schedule_run` / `_on_coordination_unavailable` | 891-975 | metadata stamp patterns to reuse | F004 |

### 2.2 Constraints

- Every `send_*` returns `{"status": "error", ...}` and never raises. The fix must respect that convention, not wrap calls in `try/except` [F002].
- `last_status` stays the status of the **agent run** (success, error or lock_unavailable). Delivery uses separate keys (user decision U2) [F004].
- `AgentSchedule.metadata` is JSONB, so no migration is needed [F004].
- `_process_job_success` runs as a fire-and-forget task. It must never raise, so the new stamp has to fail safe like `_on_coordination_unavailable` [F003, F004].
- Callbacks with `persist=False` (decorator-registered tasks) must skip the DB stamp but still collect outcomes [F003].

### 2.3 Recent History

- `43f1989277` restored `notification_succeeded`, which the homologation had overwritten. `32287f3586` homologated the `send_*` wrappers, so the failure convention is recent and deliberate [F002].
- FEAT-631 (`ed44d24fdc` … `c43993b095`) recently changed `manager.py` (coordination, `SKIPPED`). Rebase on the latest `dev` [F003].

## 3. Hypothesis / Scope

### Module 1: Callbacks report the real status (`functions/__init__.py`)
- `SendEmailReportCallback` and `SendNotifyReportCallback` return `status: "sent"` only when `self.notification_succeeded(response)` is true. Otherwise they return `{"status": "failed", "provider": …, "error": response.get("error"), "attachments": […], "response": response}` and do not raise (user decision U1).
- `SaveDataCallback` keeps `status: "saved"` for the CSV, but when an email is configured it adds `email_status: "sent" | "failed"`. A suggested refinement is to report the top-level status as `"partial"` when the save worked and the email failed. **The spec should decide this.**
- Optional: add a small `_delivery_result(response, provider, **extra)` helper on `BaseSchedulerCallback` so the three callbacks don't each re-derive the result shape.

### Module 2: The manager isolates, collects and persists (`manager.py`)
- `_handle_job_success` runs each callback inside its own `try`. It records `{"callback": name, "status": …, "error": …}`, treating both a returned `status == "failed"` and a raised exception as failures. It always continues to the next callback and to `send_result` (user decision U3). It returns the list of outcomes.
- `_send_result_email` returns the notifier result. Its outcome is recorded as `{"callback": "send_result", …}` and checked with `notification_succeeded`.
- `_process_job_success` (when `persist=True`) adds a second, fail-safe stamp after callbacks run: `metadata.last_callbacks = [...]`, `metadata.last_delivery_status = "ok" | "partial" | "failed"` (or no key/`"none"` when no callbacks are configured), and `metadata.last_delivery_time`. A failure is logged at `warning` level, with schedule_id and callback name.
- `last_status`, `run_count` and `last_run` do not change.

### Explicitly NOT in scope
- Changing `NotificationMixin` or the `send_*` failure convention (the issue's proposed fix point is the callers).
- Retrying failed deliveries.
- Exposing `last_delivery_status` in the admin UI or handlers. A possible follow-up.
- async-notify pins (environment drift, already resolved).

### Test plan sketch
- Unit tests (`packages/ai-parrot/tests/scheduler/` or the server tests): patch `send_email`/`send_notification` to return `{"status": "error"}` and `{"status": "success"}`, then assert the callback status is `failed`/`sent`. Do the same for the `SaveDataCallback` email path.
- Manager tests (`packages/ai-parrot-server/tests/scheduler/`):
  - A raising first callback still runs the second callback and `send_result`.
  - Outcomes are returned.
  - With a mocked pool, the stamp writes `last_callbacks`/`last_delivery_status` and leaves `last_status="success"`.
  - `persist=False` skips the stamp.

## 4. Confidence Map

| Claim | Confidence | Evidence |
|---|---|---|
| C1: the callbacks hard-code `"sent"` | high | F001 |
| C2: `notification_succeeded` is the existing predicate; `send_*` never raise | high | F002 |
| C3: the manager discards outcomes, doesn't isolate callbacks, stamps before callbacks | high | F003 |
| C4: persisting in metadata JSONB needs no DDL | high | F004 |
| C5: no behavioural tests exist for callbacks | high | F005 |
| `SaveDataCallback` top-level status on email failure (`saved` + `email_status` vs `partial`) | medium | design choice, left to the spec |

## 5. Open Questions

### Resolved (2026-10-05)
- [x] **U1: How a callback fails.** Return `status: "failed"` (no raise), matching the `NotificationMixin` never-raise convention.
- [x] **U2: Persistence.** Separate keys: `metadata.last_delivery_status` (`ok|partial|failed`) plus `metadata.last_callbacks[]`. `last_status` stays the agent-run status.
- [x] **U3: Isolation.** Keep going: each callback is isolated, and failures are recorded but don't stop the others.

### Unresolved
- [ ] Whether `SaveDataCallback`'s top-level status should become `"partial"` when the email fails, or stay `"saved"` with `email_status`. Decide in `/sdd-spec`.

## 6. Recommended Next Step

→ `/sdd-spec sdd/proposals/gh-1574-scheduler-callback-delivery-status.proposal.md`

Rationale: localization is high-confidence, limited to two files in one package, and every material design decision is resolved. Expect about 2–3 tasks: callbacks, manager, and tests.

## 7. Research Audit

- State: `sdd/state/GH-1574/state.json` (budget `default`: 6 files read, 6 greps, 2 git calls, not truncated)
- Findings: F001 (callbacks), F002 (predicate), F003 (manager), F004 (metadata pattern), F005 (tests and env)
- Synthesis: `sdd/state/GH-1574/synthesis.json`
