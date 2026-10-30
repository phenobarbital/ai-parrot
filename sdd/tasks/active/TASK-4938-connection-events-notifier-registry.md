# TASK-4938: Connection events, ChannelNotifier registry and publisher

**Feature**: FEAT-773 — Delegated Auth Connections — S-1 Connections Core
**Spec**: `sdd/specs/delegated-auth-connections.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Completion" and §3 Module 4 (U5, S6). Callbacks stop dispatching completion by direct in-process
calls into channel code. Instead the engine hands a `ConnectionEvent` (no token material) to a
`ConnectionEventPublisher`, which (1) awaits the `ChannelNotifier` registered for `event.channel` — the
load-bearing path, (2) appends an `AuditLedger` entry, (3) publishes on an optional publish-only Streams bus.
A failing notifier is logged and never fails the callback.

---

## Scope

- Create `parrot/auth/oauth2/events.py`: `ConnectionEventKind`, `ConnectionEvent`, `ChannelNotifier` Protocol,
  `ChannelNotifierRegistry` singleton (register/get/all/_reset — same shape as `OAuth2ProviderRegistry`),
  `ConnectionEventPublisher` (publish/shutdown, notifier → audit → bus, never raises),
  `setup_connection_fanout(bus)` reusing the `_validate_bus` rule from `observability/fanout.py`.
- Log a warning when no notifier is registered for `event.channel` (S6 topology gotcha).
- Unit tests `test_event_publisher_order_and_isolation`, `test_setup_connection_fanout_requires_publish_only_streams`.

**NOT in scope**: channel adapters (TASK-4953); calling the publisher from managers (TASK-4940/4941); exports from `oauth2/__init__.py` (TASK-4949).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/events.py` | CREATE | events, notifier registry, publisher, fan-out setup |
| `packages/ai-parrot/tests/unit/auth/test_connection_events.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified against `dev` @ `a848d5a73e` (2026-10-30) while writing this task.
> Use these exact imports and signatures. Anything not listed: VERIFY it exists before using it.

### Verified Imports
```python
from parrot.security.audit_ledger import AuditLedger              # verified: security/audit_ledger.py:296
from parrot.observability.fanout import _validate_bus             # verified: observability/fanout.py:74
from pydantic import BaseModel
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/security/audit_ledger.py:338
class AuditLedger:
    async def append(self, *, user_id: str, channel: str, tool: str, provider: str,
                     credential_material: Any) -> AuditLedgerEntry: ...   # material is fingerprinted, never stored

# packages/ai-parrot/src/parrot/observability/fanout.py:74
def _validate_bus(bus: Any) -> None   # RuntimeError unless transport == "streams" and publish_only is True

# navigator_eventbus.evb.EventBus (installed 0.4.0) — publish-only bus API used here
async def emit(self, event_type: str, payload: Dict[str, Any], **kwargs) -> int   # evb.py:457

# packages/ai-parrot/src/parrot/auth/oauth2/registry.py:69 — singleton shape to copy
class OAuth2ProviderRegistry:
    _instance: ClassVar[Optional["OAuth2ProviderRegistry"]] = None
    def __new__(cls): ...            # creates _instance and _providers = {}
    @classmethod
    def _reset(cls) -> None: cls._instance = None
```

### Does NOT Exist
- ~~`parrot.auth.oauth2.events`~~ — created by this task.
- ~~a consuming `navigator_eventbus` subscriber in `integrations/telegram|slack|msteams`~~ — none; the bus is publish-only.
- ~~`UserSocketManager.send_to_principal`~~ — out of scope (S-3a).
- ~~`AuditLedger.log` / `AuditLedger.record`~~ — the method is `append` (keyword-only).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/events.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_connection_events.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/security/audit_ledger.py#AuditLedger.append",
    "sym:packages/ai-parrot/src/parrot/observability/fanout.py#_validate_bus"
  ]
}
```

---

## Implementation Notes

- `credential_material=f"{event.kind}:{event.account_id}"` — the ledger fingerprints it; never pass a token.
- Bus payload = `event.model_dump(mode="json")`; event type = `event.kind`. Bus errors are logged, not raised.
- Notifier exceptions are caught with `self.logger.exception(...)`; order is notifier → audit → bus.

---

## Implementation Blueprint

> Executor-ready starting point. Write each block to its declared path, then complete every
> `# FILL IN:` marker. Business branches, edge cases and test bodies are stubs by design.
> Never change a signature, class name or file path the blueprint fixes.

### Steps (in order)
1. Write `events.py` from the block — *why*: the §2 models are fixed; the publisher order is spec §3 M4.
2. Implement the FILL IN publisher body — *why*: S6 isolation (a raising notifier never fails a callback).
3. Write both tests — *why*: spec §4 M4 rows.

### `packages/ai-parrot/src/parrot/auth/oauth2/events.py` (CREATE)
```python
"""Connection lifecycle events (FEAT-773 M4): notifier registry + audit + optional bus."""
from __future__ import annotations

import logging
from typing import Any, ClassVar, Dict, List, Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel

from parrot.security.audit_ledger import AuditLedger

logger = logging.getLogger(__name__)

ConnectionEventKind = Literal["connection.completed", "connection.revoked", "connection.refresh_failed"]


class ConnectionEvent(BaseModel):
    """A connection state change. Never carries token material."""

    kind: ConnectionEventKind
    user_id: str
    canonical_identity: Optional[str] = None
    tenant_id: Optional[str] = None
    provider: str
    account_id: str = ""
    display_name: str = ""
    channel: str
    occurred_at: float
    reason: Optional[str] = None


@runtime_checkable
class ChannelNotifier(Protocol):
    """Delivers a connection event to the user on one channel (may raise; the publisher logs)."""

    channel: str

    async def notify(self, event: ConnectionEvent, state_payload: Dict[str, Any]) -> None: ...


class ChannelNotifierRegistry:
    """Process-wide singleton: one notifier per channel."""

    _instance: ClassVar[Optional["ChannelNotifierRegistry"]] = None
    _notifiers: Dict[str, ChannelNotifier]

    def __new__(cls) -> "ChannelNotifierRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._notifiers = {}
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        cls._instance = None

    def register(self, notifier: ChannelNotifier) -> None:
        """Register (or replace) the notifier for ``notifier.channel``."""
        self._notifiers[notifier.channel] = notifier

    def get(self, channel: str) -> Optional[ChannelNotifier]:
        return self._notifiers.get(channel)

    def all(self) -> List[ChannelNotifier]:
        return list(self._notifiers.values())


class ConnectionEventPublisher:
    """notifier (load-bearing) → audit ledger → publish-only bus (additive). Never raises."""

    def __init__(self, *, notifiers: Optional[ChannelNotifierRegistry] = None,
                 audit_ledger: Optional[AuditLedger] = None, bus: Any = None) -> None:
        self._notifiers = notifiers if notifiers is not None else ChannelNotifierRegistry()
        self._audit = audit_ledger
        self._bus = bus
        self.logger = logger

    def attach_bus(self, bus: Any) -> None:
        """Attach a validated publish-only Streams bus."""
        _validate_connection_bus(bus)
        self._bus = bus

    async def publish(self, event: ConnectionEvent, state_payload: Optional[Dict[str, Any]] = None) -> None:
        """Deliver ``event``; every stage's failure is logged and swallowed."""
        # FILL IN: 1) notifier = self._notifiers.get(event.channel); None → self.logger.warning(...);
        #          else await notifier.notify(event, state_payload or {}) inside try/except → logger.exception
        #          2) if self._audit: await self._audit.append(user_id=event.user_id, channel=event.channel,
        #             tool="connections", provider=event.provider,
        #             credential_material=f"{event.kind}:{event.account_id}") in try/except
        #          3) if self._bus: await self._bus.emit(event.kind, event.model_dump(mode="json")) in try/except
        #          — bounded by AC-7 (order + isolation) and S6
        raise NotImplementedError

    async def shutdown(self) -> None:
        """Close the bus if attached (FILL IN: await bus.close() when present, swallow errors); detach it."""
        # FILL IN: mirror shutdown_event_fanout (fanout.py:123) — close, log, set self._bus = None
        raise NotImplementedError


def _validate_connection_bus(bus: Any) -> None:
    """Same rule as observability fan-out: transport='streams' and publish_only=True."""
    from parrot.observability.fanout import _validate_bus  # local: keeps navigator_eventbus import lazy

    _validate_bus(bus)


def setup_connection_fanout(bus: Any, publisher: Optional[ConnectionEventPublisher] = None) -> None:
    """Validate ``bus`` and attach it to ``publisher`` (raises RuntimeError on a non publish-only bus)."""
    # FILL IN: _validate_connection_bus(bus); if publisher is given call publisher.attach_bus(bus) — bounded by
    #          spec §3 M4 skeleton (rule copied from fanout.py:74-87)
    raise NotImplementedError
```
**Why this shape**: `ConnectionEvent` and the Protocol are the §2/§3 contracts. The registry copies the
`OAuth2ProviderRegistry` singleton pattern so tests reset it with `_reset()`. `setup_connection_fanout` takes an
optional publisher (the spec skeleton names only `bus`; the extra keyword keeps it usable without a module
global). The fan-out import is local because `observability.fanout` imports `navigator_eventbus` at module load.

### FILL IN checklist
- [ ] `events.py::ConnectionEventPublisher.publish` — three guarded stages in order; bounded by AC-7
- [ ] `events.py::ConnectionEventPublisher.shutdown` — close + detach; bounded by fanout.py:123 pattern
- [ ] `events.py::setup_connection_fanout` — validate + attach; bounded by fanout.py:74-87
- [ ] `test_connection_events.py` — test bodies

---

## Acceptance Criteria

- [ ] Publisher order is notifier → audit → bus; a raising notifier is logged and `publish` returns normally (AC-7)
- [ ] Missing notifier for a channel logs a warning and still audits/publishes
- [ ] `setup_connection_fanout` raises `RuntimeError` for a bus that is not streams + publish_only
- [ ] No token material in events, audit material or bus payload

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_connection_events.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_connection_events.py
import time
import pytest
from parrot.auth.oauth2.events import (ChannelNotifierRegistry, ConnectionEvent, ConnectionEventPublisher,
                                       setup_connection_fanout)


@pytest.fixture
def notifier_registry():
    ChannelNotifierRegistry._reset()
    yield ChannelNotifierRegistry()
    ChannelNotifierRegistry._reset()


def _event(**kw):
    return ConnectionEvent(kind="connection.completed", user_id="1042", provider="jira",
                           account_id="acc-1", channel="telegram", occurred_at=time.time(), **kw)


@pytest.mark.asyncio
async def test_event_publisher_order_and_isolation(notifier_registry):
    calls = []
    class Boom:
        channel = "telegram"
        async def notify(self, event, state):
            calls.append("notifier"); raise RuntimeError("down")
    class Ledger:
        async def append(self, **kw):
            calls.append("audit"); assert "acc-1" in kw["credential_material"]
    class Bus:
        async def emit(self, kind, payload):
            calls.append("bus"); assert "access_token" not in payload
    notifier_registry.register(Boom())
    await ConnectionEventPublisher(notifiers=notifier_registry, audit_ledger=Ledger(), bus=Bus()).publish(_event())
    assert calls == ["notifier", "audit", "bus"]


def test_setup_connection_fanout_requires_publish_only_streams():
    class Bad:
        transport = "pubsub"; publish_only = False
    with pytest.raises(RuntimeError):
        setup_connection_fanout(Bad())
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug delegated-auth-connections --feature-id FEAT-773`)
2. **Read the spec** (`sdd/specs/delegated-auth-connections.spec.md`) — at least §2, the module section named in Context, §5 and §7
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/delegated-auth-connections.json`
4. **Verify the Codebase Contract** before writing ANY code (re-grep each anchor; line numbers drift). If an entry is stale, fix the contract in this file first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`; never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH` set to every touched `packages/<dist>/src` (the shared `.venv` imports the main checkout otherwise)
8. **Commit the code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> delegated-auth-connections verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
