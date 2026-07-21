# TASK-1787: NotificationSubscriber — severity alerting via parrot.notifications

**Feature**: FEAT-310 — Unified EventBus v2 — queue-based dispatch, severity, ingress channels, and notifications
**Spec**: `sdd/specs/eventbus-v2.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1784
**Assigned-to**: unassigned

---

## Context

Module 5 of FEAT-310 (spec §3) — goal G3's alerting half. Subscribes to the
bus with severity thresholds and sliding-window rules, delivering alerts
through `parrot.notifications` (async-notify: email/Slack/Telegram/Teams).
⚠️ The brainstorm's suggestion of `hooks/messaging.py` was CORRECTED in the
spec: that module is inbound-only; delivery goes through
`NotificationMixin.send_notification()`.

---

## Scope

- Implement `subscribers/notification.py`:
  - `NotificationSubscriber` — registers on a `BusCore` with
    `min_severity` threshold subscriptions and/or sliding-window rate rules
    ("N events ≥ ERROR in M seconds").
  - Delivery via `NotificationMixin.send_notification()` (async-notify),
    provider/recipients per rule.
  - Rate-limiting/dedup defaults (spec §2, *resolved in brainstorm*):
    - Dedup: identical `(rule_id, topic_class)` suppressed for **300 s**
      after first delivery; repeat count appended when window closes.
    - Global throttle: max **10 notifications/min per channel**; overflow
      folded into a single digest message.
    - Storm guard: > **25 ERROR+ events / 30 s** collapses into one
      CRITICAL "event storm" alert until the rate drops.
  - All three knobs configurable via `[bus.alerts]` / `[[bus.alerts]]`
    TOML (navconfig) rule entries.
- Guard against alert loops: internal `bus.*` topics are excluded/capped
  below the alert threshold by default; subscriber's own failures must NOT
  cascade (model B — they surface as `bus.subscriber_error` only).
- Unit tests with `send_notification` mocked.

**NOT in scope**: DLQ (TASK-1788), audit/metrics subscribers (TASK-1792),
facade config for `[bus]` core section (TASK-1786).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/bus/subscribers/__init__.py` | CREATE | exports |
| `packages/ai-parrot/src/parrot/core/events/bus/subscribers/notification.py` | CREATE | `NotificationSubscriber` + rule models |
| `packages/ai-parrot/tests/core/events/bus/test_notification_subscriber.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` 2026-07-16 (commit b7226186d).

### Verified Imports
```python
from parrot.notifications import NotificationMixin        # notifications/__init__.py:56
from parrot.core.events.bus.core import BusCore           # TASK-1784
from parrot.core.events.bus.envelope import EventEnvelope, Severity  # TASK-1783
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/notifications/__init__.py:56
class NotificationMixin:
    async def send_notification(                           # line 131
        self, message, recipients,
        provider=NotificationProvider.EMAIL,
        subject=None, report=None, template=None,
        with_attachments=True, provider_options=None, **kwargs
    ) -> Dict[str, Any]
    # convenience wrappers exist: send_email / send_slack_message /
    # send_telegram_message / send_teams_message
```

### Does NOT Exist
- ~~Outbound send methods in `parrot/core/hooks/messaging.py`~~ — INBOUND-ONLY webhook receivers (`_handle_telegram/_handle_whatsapp/_handle_teams`); NOT a delivery channel. Use `NotificationMixin`.
- ~~Slack or email hooks in `hooks/messaging.py`~~ — only Telegram/WhatsApp/MSTeams, all inbound.
- ~~`NotificationSubscriber` / alerting rules anywhere~~ — created by THIS task.
- ~~A `[bus.alerts]` config section~~ — created by THIS task.

---

## Implementation Notes

### Pattern to Follow
Rule models as Pydantic (`BaseModel`, `extra="forbid"`): `AlertRule(rule_id,
pattern, min_severity, window_seconds, count_threshold, provider, recipients,
...)`. The subscriber is composed WITH a `NotificationMixin`-derived sender
(either subclass or accept an injected sender object exposing
`send_notification`) so tests can inject a mock.

### Key Constraints
- Sliding windows and throttles must be monotonic-clock based
  (`asyncio.get_running_loop().time()`), not wall-clock.
- Digest/storm messages carry counts and first/last topic examples.
- Never `await send_notification` inside the bus dispatch path unshielded —
  deliver from the subscriber's own task context; a hung provider must not
  stall bus workers (use timeout).
- `self.logger` via navconfig logging; strict typing; Google docstrings.

### References in Codebase
- `packages/ai-parrot/src/parrot/notifications/__init__.py` — delivery API + provider enum
- `packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py` — subscriber error-isolation style

---

## Acceptance Criteria

- [ ] Severity threshold rule: ERROR envelope triggers exactly one `send_notification` call (mock asserted).
- [ ] Sliding-window rule: "N-in-M-seconds" fires once when crossed, not per event.
- [ ] 300 s dedup window suppresses identical `(rule_id, topic_class)` repeats; repeat count reported on window close.
- [ ] 10/min channel throttle folds overflow into a single digest.
- [ ] Storm guard: >25 ERROR+ / 30 s → one CRITICAL storm alert, then silence until rate drops.
- [ ] Internal `bus.*` topics never trigger alerts with default config.
- [ ] All knobs overridable via `[bus.alerts]` TOML.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/core/events/bus/test_notification_subscriber.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/bus/subscribers/` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/core/events/bus/test_notification_subscriber.py
import pytest


@pytest.fixture
def mock_notify(monkeypatch):
    """Patches/injects send_notification; records calls."""
    ...

async def test_notification_threshold_rule(mock_notify): ...
async def test_notification_rate_window_rule(mock_notify): ...
async def test_notification_dedup_and_storm_collapse(mock_notify): ...
async def test_channel_throttle_digest(mock_notify): ...
async def test_bus_internal_topics_never_alert(mock_notify): ...
```

---

## Agent Instructions

1. Read spec §2 (Egress + rate-limit defaults) and §7 ("Alert storms") first.
2. Verify TASK-1784 is in `sdd/tasks/completed/`.
3. Verify the `NotificationMixin.send_notification` signature before coding.
4. Update `sdd/tasks/index/eventbus-v2.json` status transitions.
5. Move this file to `sdd/tasks/completed/` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-16
**Notes**: `NotificationSubscriber` + Pydantic `AlertRule`/`AlertsConfig` (extra=forbid). Threshold rules and sliding-window rules ("N events >= severity in M s", fire once per crossing). Spec §2 defaults: 300s dedup per (rule_id, topic_class) with repeat count appended when window closes; 10/min channel throttle with overflow folded into ONE digest per window; storm guard >25 ERROR+/30s → single CRITICAL alert, per-rule alerts suppressed until rate drops. All monotonic-clock based (loop.time()). Delivery via injected sender's send_notification (NotificationMixin-compatible) as create_task with asyncio.timeout — never stalls bus workers; failures logged only (model B). bus.* topics excluded by default (include_bus_internal knob). Config: AlertsConfig.from_navconfig() for scalar BUS_ALERTS_* knobs; AlertsConfig.from_dict() for full [bus.alerts]/[[bus.alerts]] TOML mappings incl. rules. 10 unit tests pass; ruff clean.

**Deviations from spec**: throttle window length exposed as an extra knob (`channel_throttle_window_seconds`, default 60s → 10/min as specified) for testability; storm alert uses the first rule's provider/recipients (no dedicated storm channel was specified).
