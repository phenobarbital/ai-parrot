# TASK-1786: EventBus facade — legacy API preserved over BusCore

**Feature**: FEAT-310 — Unified EventBus v2 — queue-based dispatch, severity, ingress channels, and notifications
**Spec**: `sdd/specs/eventbus-v2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1785
**Assigned-to**: unassigned

---

## Context

Module 4 of FEAT-310 (spec §3) — the non-breaking migration keystone (goal
G6). `EventBus` in `evb.py` becomes a thin facade over `BusCore`: every
existing caller (`EventRegistry.forward_to_bus`, `HookManager.set_event_bus`,
`AutonomousOrchestrator`, `EvalRunner`, `AbstractBot`, `WebhookListener`)
keeps working with ZERO changes. The existing guard-rail tests
(`test_eventbus_imports.py`, `test_hookmanager_eventbus.py`) must pass
UNMODIFIED.

---

## Scope

- Rewrite `evb.py` internals: `EventBus` delegates to `BusCore` +
  `MemoryBackend`/`RedisPubSubBackend` (Redis URL kwarg behavior preserved).
- PRESERVE verbatim public signatures: `subscribe(pattern, handler, *,
  priority=0, filter_fn=None) -> str`, `unsubscribe(id) -> bool`,
  `publish(event: Event) -> int`, `emit(event_type, payload, **kwargs) -> int`,
  `on(pattern, **kwargs)` decorator, `close()`. New kwargs
  (`severity=...`, `min_severity=...`) are ADDITIVE-ONLY with defaults.
- Internal `Event ↔ EventEnvelope` conversion via TASK-1783 converters.
- `publish()`/`emit()` keep returning `int` (subscriber match count at
  enqueue time) but MUST NOT await handlers.
- Keep `Event`, `EventPriority`, `EventSubscription` classes exported;
  `events/__init__.py` continues exporting exactly the four names.
- `_event_history` behavior: keep the attribute + `get_history()`-style
  accessors if present, backed by a bounded deque (compat shim).
- Remove `start_redis_listener()` body → delegate to `RedisPubSubBackend`
  (method kept as deprecated alias that starts the backend consumer).
- `[bus]` TOML config parsing (navconfig) for workers/queue/backpressure/
  backend selection, applied in `EventBus.__init__`.
- Fix the naive `datetime.now()` default in legacy `Event` (line 29) →
  tz-aware UTC (spec Problem Statement lists it as a defect; converters
  still coerce for externally-built events).

**NOT in scope**: hooks routing changes (TASK-1790), notification/DLQ/audit
subscribers (TASK-1787/1788/1792), Streams backend (TASK-1789).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/evb.py` | MODIFY | facade rewrite — API preserved |
| `packages/ai-parrot/src/parrot/core/events/__init__.py` | MODIFY only if needed | MUST keep exporting exactly `EventBus`, `Event`, `EventPriority`, `EventSubscription` |
| `packages/ai-parrot/tests/core/events/bus/test_facade.py` | CREATE | `test_facade_signatures_unchanged` + behavior tests |

> **Guard rails — must pass UNMODIFIED:**
> `packages/ai-parrot/tests/core/events/test_eventbus_imports.py`
> `packages/ai-parrot/tests/core/hooks/test_hookmanager_eventbus.py`

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` 2026-07-16 (commit b7226186d).

### Verified Imports
```python
from parrot.core.events import EventBus, Event, EventPriority, EventSubscription  # __init__.py:13-20
from parrot.core.events.bus.core import BusCore                                    # TASK-1784
from parrot.core.events.bus.converters import from_legacy_event                    # TASK-1783
from parrot.core.events.bus.backends.memory import MemoryBackend                   # TASK-1785
from parrot.core.events.bus.backends.redis_pubsub import RedisPubSubBackend        # TASK-1785
```

### Existing Signatures to Use (preserve VERBATIM)
```python
# packages/ai-parrot/src/parrot/core/events/evb.py
class EventPriority(Enum):                            # line 15 — unchanged
@dataclass
class Event:                                          # line 24 — keep fields; fix naive default (line 29)
    def to_dict(self) -> Dict[str, Any]               # line 35
    @classmethod
    def from_dict(cls, data) -> "Event"               # line 48
@dataclass
class EventSubscription:                              # line 62 — keep (part of public exports)
class EventBus:                                       # line 72
    CHANNEL_PREFIX = "parrot:events:"                 # line 83
    async def close(self)                             # line 117
    def subscribe(self, pattern, handler, *, priority=0, filter_fn=None) -> str   # line 129
    def unsubscribe(self, subscriber_id: str) -> bool # line 171
    async def publish(self, event: Event) -> int      # line 188
    async def start_redis_listener(self)              # line 257 — becomes deprecated alias
    async def emit(self, event_type, payload, **kwargs) -> int   # line 294
    def on(self, pattern: str, **kwargs)              # line 308

# Injection sites that must keep working UNCHANGED (verify after rewrite):
# lifecycle/registry.py:283  — asyncio.create_task(self._event_bus.emit(channel, dict))
# hooks/manager.py:43        — set_event_bus(bus); dual-emit "hooks.<type>.<event>"
# ai-parrot-server .../autonomous/orchestrator.py:231 — self.event_bus = EventBus(...)
# parrot/eval/runner.py:144,504 · parrot/bots/abstract.py:303,451 · autonomous/webhooks.py:65
```

### Does NOT Exist
- ~~`EventBus.publish_envelope()` or any envelope-typed public method~~ — envelopes stay INTERNAL to the facade in this task; new public surface comes later if ever.
- ~~`close()`/`punsubscribe()` bug~~ — ALREADY FIXED on dev (evb.py:124). Do NOT "re-fix".
- ~~Config section `[bus]`~~ — created by THIS task (navconfig TOML).
- ~~Any call site passing positional `filter_fn` or `priority`~~ — they are kw-only today; keep them kw-only.

---

## Implementation Notes

### Pattern to Follow
```python
class EventBus:
    def __init__(self, redis_url: str | None = None, **kwargs):
        backend = RedisPubSubBackend(redis_url) if redis_url else MemoryBackend()
        self._core = BusCore(backend=backend, **core_opts_from_config(kwargs))
    async def emit(self, event_type, payload, **kwargs) -> int:
        envelope = from_legacy_event(Event(event_type=event_type, payload=payload, **legacy_kwargs))
        matches = self._core.count_matches(event_type)   # cheap, sync
        await self._core.publish(envelope)               # O(1) enqueue
        return matches
```

### Key Constraints
- Lazy start: current `EventBus` works without an explicit `start()`; the
  facade must auto-start `BusCore` on first publish/emit (or in `__init__`
  when a running loop exists) so existing call sites need no changes.
- Return count semantics: `int` = subscribers matched at enqueue time
  (delivery is now async — document the semantic shift in the docstring).
- Handler kwarg names in `subscribe()` are load-bearing (call sites use
  `priority=`, `filter_fn=`) — verify with grep before finalizing.
- Run BOTH guard-rail test files plus the full events/hooks test dirs.

### References in Codebase
- `packages/ai-parrot/tests/core/events/test_eventbus_imports.py` — export contract
- `packages/ai-parrot/tests/core/hooks/test_hookmanager_eventbus.py` — dual-emit contract

---

## Acceptance Criteria

- [ ] `test_eventbus_imports.py` and `test_hookmanager_eventbus.py` pass UNMODIFIED.
- [ ] `events/__init__` exports exactly `EventBus`, `Event`, `EventPriority`, `EventSubscription`.
- [ ] `publish()`/`emit()` return without awaiting any handler (slow-handler test).
- [ ] `EventRegistry.forward_to_bus` and `HookManager.set_event_bus` work with zero call-site changes (integration-style test through the facade).
- [ ] New kwargs (`severity=`, `min_severity=`) are additive; all legacy call shapes still typecheck/run.
- [ ] `[bus]` TOML section parsed via navconfig with documented defaults.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/core/events/ packages/ai-parrot/tests/core/hooks/ -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/core/events/bus/test_facade.py
import pytest
from parrot.core.events import EventBus, Event, EventPriority, EventSubscription


async def test_facade_signatures_unchanged():
    bus = EventBus()
    sid = bus.subscribe("a.*", handler, priority=5, filter_fn=lambda e: True)
    assert isinstance(sid, str)
    n = await bus.emit("a.b", {"k": 1})
    assert isinstance(n, int)
    assert bus.unsubscribe(sid) is True

async def test_emit_does_not_await_handlers(): ...
async def test_severity_kwargs_additive(): ...
async def test_lifecycle_dual_emit_through_facade(): ...
```

---

## Agent Instructions

1. Read spec §2 "Facade", §6 injection-site table, and BOTH guard-rail tests FIRST.
2. Verify TASK-1785 is in `sdd/tasks/completed/`.
3. Grep all `subscribe(`/`emit(`/`publish(` call sites before changing any signature detail.
4. Update `sdd/tasks/index/eventbus-v2.json` status transitions.
5. Move this file to `sdd/tasks/completed/` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
