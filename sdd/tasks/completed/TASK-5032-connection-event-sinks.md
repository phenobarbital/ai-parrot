# TASK-5032: Channel-independent connection event sinks on the publisher

**Feature**: FEAT-777 — Connections — Web + Slack
**Spec**: `sdd/specs/connections-web-slack.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

S-1's `ConnectionEventPublisher` delivers each event only to the notifier of `event.channel`. The web
Connections panel must see *every* event of its principal, whatever channel produced it (spec §2 "Push (M1, D1)").
This task adds a second, channel-independent delivery list — `ConnectionEventSink`s — that the server's
`RedisConnectionPush` (TASK-5033) registers on. Implements spec §3 Module 1 (core part).

---

## Scope

- Add the `ConnectionEventSink` Protocol (`async deliver(event)`), runtime-checkable, to `parrot/auth/oauth2/events.py`.
- Add `ConnectionEventPublisher.add_sink(sink)` and a private `self._sinks` list initialised in `__init__`.
- In `publish()`, call every sink **after** the channel notifier and **before** audit and bus
  (order: notifier → sinks → audit → bus), each isolated: an exception is logged with `self.logger.exception` and the
  next sink still runs; `publish()` never raises.
- `add_sink` is idempotent for the same object (adding the same instance twice registers it once).
- Write unit tests.

**NOT in scope**: `RedisConnectionPush` (TASK-5033), the SSE handler and startup wiring (TASK-5040), any export from
`parrot/auth/oauth2/__init__.py` (owned by TASK-5035 — import from `parrot.auth.oauth2.events` directly).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/events.py` | MODIFY | `ConnectionEventSink` Protocol, `add_sink`, sink stage in `publish` |
| `packages/ai-parrot/tests/unit/auth/test_connection_event_sinks.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.oauth2.events import (                     # verified: packages/ai-parrot/src/parrot/auth/oauth2/events.py
    ConnectionEvent,               # :17
    ChannelNotifier,               # :33 (runtime_checkable Protocol, attr `channel`, async notify(event, state_payload))
    ChannelNotifierRegistry,       # :41 (process-wide singleton; classmethod _reset() :54)
    ConnectionEventPublisher,      # :70
)
# events.py already imports: Any, ClassVar, Dict, List, Literal, Optional, Protocol, runtime_checkable (:6)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/events.py
ConnectionEventKind = Literal["connection.completed", "connection.revoked", "connection.refresh_failed"]  # :14
class ConnectionEvent(BaseModel):                           # :17
    kind: ConnectionEventKind; user_id: str; canonical_identity: Optional[str] = None; tenant_id: Optional[str] = None
    provider: str; account_id: str = ""; display_name: str = ""; channel: str; occurred_at: float; reason: Optional[str] = None
class ConnectionEventPublisher:                             # :70
    def __init__(self, *, notifiers: Optional[ChannelNotifierRegistry] = None,
                 audit_ledger: Optional[AuditLedger] = None, bus: Any = None) -> None   # :73-83 (self.logger = logger :83)
    def attach_bus(self, bus: Any) -> None                  # :85
    async def publish(self, event: ConnectionEvent, state_payload: Optional[Dict[str, Any]] = None) -> None  # :89
        # notifier block :91-98, then `if self._audit is not None:` :101, then bus block
    async def shutdown(self) -> None
```

### Does NOT Exist
- ~~`ConnectionEventPublisher.add_sink`~~, ~~`ConnectionEventSink`~~, ~~`self._sinks`~~ — created by this task.
- ~~A sink/listener list on `ChannelNotifierRegistry`~~ — the registry holds one notifier per channel only; do not put sinks there.
- ~~`ConnectionEventPublisher.remove_sink`~~ — not required; do not add.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/auth/oauth2/events.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/auth/test_connection_event_sinks.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ConnectionEventPublisher",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ConnectionEvent",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/events.py#ChannelNotifierRegistry"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Core never imports server or integrations code; the Protocol lives here so the server can implement it.
- Sinks run even when no notifier is registered for `event.channel` (the warning branch) — the panel must
  receive Telegram/Slack events although the web channel has no notifier.
- A sink must never block the notifier: the notifier runs first (it is load-bearing for the originating channel).
- Do not add `__init__.py` exports (file owned by TASK-5035).

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/oauth2/events.py:89-124` — the existing isolation pattern for each stage.
- `packages/ai-parrot/tests/unit/auth/test_connection_events.py` — existing publisher tests (fixture style).

---

## Implementation Blueprint

### Steps (in order)
1. Add the `ConnectionEventSink` Protocol right after `ChannelNotifier` — *why*: it sits with the other delivery Protocols and must be defined before the publisher uses it in annotations.
2. Initialise `self._sinks: List[ConnectionEventSink] = []` in `__init__` and add `add_sink` after `attach_bus` — *why*: registration happens at server setup, before any event.
3. Insert the sink loop between the notifier block and the audit block in `publish` — *why*: spec fixes the order notifier → sinks → audit → bus.
4. Write the tests, then run the Validation Commands.

### `packages/ai-parrot/src/parrot/auth/oauth2/events.py` (MODIFY — Protocol)
```python
# occurrences: 1 (verified: grep -c 'class ChannelNotifierRegistry:' packages/ai-parrot/src/parrot/auth/oauth2/events.py)
# BEFORE — insert above `class ChannelNotifierRegistry:` (verified: events.py:41)
@runtime_checkable
class ConnectionEventSink(Protocol):
    """Receives every connection event regardless of ``event.channel`` (FEAT-777 M1).

    May raise; the publisher logs the failure and continues with the next stage.
    """

    async def deliver(self, event: ConnectionEvent) -> None: ...
```

### `packages/ai-parrot/src/parrot/auth/oauth2/events.py` (MODIFY — init + add_sink)
```python
# occurrences: 1 (verified: grep -c '        self.logger = logger' packages/ai-parrot/src/parrot/auth/oauth2/events.py)
# AFTER — insert below `        self.logger = logger` (verified: events.py:83)
        self._sinks: List[ConnectionEventSink] = []

# occurrences: 1 (verified: grep -c '    def attach_bus(self, bus: Any) -> None:' packages/ai-parrot/src/parrot/auth/oauth2/events.py)
# BEFORE — insert above `    def attach_bus(self, bus: Any) -> None:` (verified: events.py:85)
    def add_sink(self, sink: ConnectionEventSink) -> None:
        """Register a channel-independent sink, called for every published event.

        Order inside :meth:`publish`: notifier → sinks → audit → bus. Adding the same
        instance twice registers it once.
        """
        # FILL IN: identity-based dedupe (`any(s is sink for s in self._sinks)`), then append — bounded by "idempotent per instance"
```

### `packages/ai-parrot/src/parrot/auth/oauth2/events.py` (MODIFY — publish)
```python
# occurrences: 1 (verified: grep -c '        if self._audit is not None:' packages/ai-parrot/src/parrot/auth/oauth2/events.py)
# BEFORE — insert above `        if self._audit is not None:` (verified: events.py:101)
        for sink in list(self._sinks):
            try:
                await sink.deliver(event)
            except Exception:  # noqa: BLE001 — a sink must never fail the callback
                self.logger.exception("Connection event sink %s failed for provider %s", type(sink).__name__, event.provider)
```
**Why**: the loop iterates a copy so a sink registering another sink mid-publish cannot mutate the list being walked; the
broad except mirrors the notifier/audit/bus stages (`publish` never raises — spec M1).

### `packages/ai-parrot/tests/unit/auth/test_connection_event_sinks.py` (CREATE)
```python
"""Tests for channel-independent connection event sinks (FEAT-777 M1)."""

from __future__ import annotations

import time

import pytest

from parrot.auth.oauth2.events import (
    ChannelNotifierRegistry,
    ConnectionEvent,
    ConnectionEventPublisher,
    ConnectionEventSink,
)


@pytest.fixture(autouse=True)
def _fresh_registry():
    ChannelNotifierRegistry._reset()
    yield
    ChannelNotifierRegistry._reset()


def _event(channel: str = "telegram") -> ConnectionEvent:
    return ConnectionEvent(kind="connection.completed", user_id="1042", provider="jira", channel=channel, occurred_at=time.time())


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[ConnectionEvent] = []

    async def deliver(self, event: ConnectionEvent) -> None:
        self.events.append(event)


class _RaisingSink:
    async def deliver(self, event: ConnectionEvent) -> None:
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_publisher_calls_sinks_for_every_channel() -> None:
    """An event for a channel with no web notifier still reaches the sink."""
    # FILL IN: publisher with no notifier for "telegram"; add _RecordingSink; publish; assert one event received
    ...


@pytest.mark.asyncio
async def test_raising_sink_is_isolated(caplog: pytest.LogCaptureFixture) -> None:
    """A raising sink is logged, later sinks still run, publish does not raise."""
    # FILL IN: [_RaisingSink(), _RecordingSink()] — second still receives the event; caplog has the sink failure
    ...


@pytest.mark.asyncio
async def test_sink_order_after_notifier_before_audit() -> None:
    """Order is notifier → sinks → audit."""
    # FILL IN: shared call-order list appended by a notifier double (channel="telegram"), a sink, and an audit double with async append(**kw)
    ...


def test_add_sink_idempotent_and_protocol() -> None:
    """Same instance registered once; recording sink satisfies the runtime Protocol."""
    # FILL IN: add twice → publisher._sinks has length 1; isinstance(_RecordingSink(), ConnectionEventSink)
    ...
```

### FILL IN checklist
- [ ] `events.py::ConnectionEventPublisher.add_sink` — identity dedupe; bounded by "idempotent per instance".
- [ ] `test_connection_event_sinks.py` — four test bodies; bounded by spec §4 `test_publisher_calls_sinks_for_every_channel` and AC-3 (any originating channel).

---

## Acceptance Criteria

- [ ] `ConnectionEventSink` and `ConnectionEventPublisher.add_sink` importable from `parrot.auth.oauth2.events`.
- [ ] Sinks receive events of every channel, including channels without a notifier.
- [ ] Order notifier → sinks → audit → bus; a raising sink is logged and `publish` does not raise.
- [ ] Existing publisher tests still pass.
- [ ] `ruff check packages/ai-parrot/src/parrot/auth/oauth2/events.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_connection_event_sinks.py -q`
- `pytest packages/ai-parrot/tests/unit/auth/test_connection_events.py -q`

---

## Test Specification

See the CREATE block above: `test_publisher_calls_sinks_for_every_channel`, `test_raising_sink_is_isolated`,
`test_sink_order_after_notifier_before_audit`, `test_add_sink_idempotent_and_protocol`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug connections-web-slack --feature-id FEAT-777`)
2. **Read the spec** at the path listed above for full context (§2 "Push (M1, D1)", §3 Module 1)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-web-slack.json`
4. **Verify the Codebase Contract** before writing code; update it first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker; never change a fixed signature or path
7. **Verify** all acceptance criteria — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `scripts/sdd/close_task.sh TASK-5032 connections-web-slack verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-terra (codex)
**Date**: 2026-10-31
**Notes**: Implemented per task; merged and merge-tier validated. Only red were 3 pre-existing failures also failing on origin/dev (test_o365_refresh x2, slack test_manager_payload_drives_identity_and_dm).

**Deviations from spec**: none | describe if any
