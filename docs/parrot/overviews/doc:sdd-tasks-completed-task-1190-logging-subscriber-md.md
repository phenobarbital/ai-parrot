---
type: Wiki Overview
title: 'TASK-1190: Implement LoggingSubscriber'
id: doc:sdd-tasks-completed-task-1190-logging-subscriber-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Module 9 of the spec. `LoggingSubscriber` is the simplest built-in subscriber:
  it logs every lifecycle event via `navconfig.logging` at a configurable level. It
  exists primarily for the basic-telemetry PoC scenario and as a default-on observability
  tool for development. It is als'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.provider
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.subscribers.logging
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1190: Implement LoggingSubscriber

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-1184
**Assigned-to**: unassigned

---

## Context

Module 9 of the spec. `LoggingSubscriber` is the simplest built-in subscriber: it logs every lifecycle event via `navconfig.logging` at a configurable level. It exists primarily for the basic-telemetry PoC scenario and as a default-on observability tool for development. It is also an `EventProvider` so it can be registered with `add_provider()` and capture every `LifecycleEvent` subclass with one call.

Spec section: §3 Module 9.

**Parallel-safe** with TASK-1186 / 1187 / 1188 / 1189 / 1191 / 1192 (different file, only depends on event classes).

---

## Scope

- Implement `LoggingSubscriber` as an `EventProvider` that subscribes to `LifecycleEvent` (the base class) — receives every event.
- Configurable log level (default `INFO`) and configurable logger name (default `parrot.lifecycle`).
- Each event is logged as a single line summarizing: event class name, source_name, source_type, trace_id, and a compact dict of non-cross-cutting fields.
- Add unit tests covering: subscription happens via `register()`, configurable level, includes trace_id in the log line.

**NOT in scope**: integration with YAML loader (TASK-1196), OTel mapping (TASK-1191), webhook delivery (TASK-1192).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/__init__.py` | CREATE | Package marker + LoggingSubscriber re-export. |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/logging.py` | CREATE | `LoggingSubscriber` provider. |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_logging_subscriber.py` | CREATE | Log-level + content tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import logging
from typing import TYPE_CHECKING

from parrot.core.events.lifecycle.base import LifecycleEvent       # TASK-1183

if TYPE_CHECKING:
    from parrot.core.events.lifecycle.registry import EventRegistry
```

### Existing Signatures to Use

```python
# Project-standard logger pattern (verified across the codebase)
from navconfig.logging import logging
logger = logging.getLogger("parrot.lifecycle")
```

```python
# parrot/core/events/lifecycle/registry.py — from TASK-1186
class EventRegistry:
    def subscribe(
        self,
        event_type: Type[E],
        callback: AsyncSubscriber,
        *,
        where=None,
        forward_to_bus: bool = False,
    ) -> str: ...
```

### Does NOT Exist

- ~~`navconfig.logging.get_event_logger`~~ — there is no specialized factory; `logging.getLogger(name)` is the pattern.
- ~~`structlog`~~ — not a project dependency.

---

## Implementation Notes

### `LoggingSubscriber` shape

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/logging.py
import logging
from typing import TYPE_CHECKING

from parrot.core.events.lifecycle.base import LifecycleEvent

if TYPE_CHECKING:
    from parrot.core.events.lifecycle.registry import EventRegistry


class LoggingSubscriber:
    """EventProvider that logs every LifecycleEvent at the configured level.

    Conforms to EventProvider Protocol (TASK-1188) by exposing register().
    """

    def __init__(
        self,
        *,
        level: int = logging.INFO,
        logger_name: str = "parrot.lifecycle",
    ) -> None:
        self._level = level
        self._logger = logging.getLogger(logger_name)

    def register(self, registry: "EventRegistry") -> None:
        registry.subscribe(LifecycleEvent, self._on_event)

    async def _on_event(self, event: LifecycleEvent) -> None:
        trace_id = event.trace_context.trace_id if event.trace_context else "-"
        # Compose a single-line summary. event.to_dict() yields a clean dict.
        # Avoid full to_dict() in the hot path — pick the structural fields.
        cls = type(event).__name__
        self._logger.log(
            self._level,
            "lifecycle %s source=%s/%s trace=%s",
            cls,
            event.source_type or "-",
            event.source_name or "-",
            trace_id,
        )
```

### Why subscribe to `LifecycleEvent` (the base)

Per the spec's dispatch rule: subscribing to the base class receives every concrete subclass. One subscription, total coverage. Cheap.

### Performance note

Avoid calling `event.to_dict()` in the hot path here. The to_dict() roundtrip is for bus serialization (TASK-1186 dispatch loop), not for human-readable logging.

### Key Constraints

- `register()` is sync.
- Callback is async (per `AsyncSubscriber` contract from TASK-1186).
- No new dependencies — stdlib + project `navconfig.logging`.

---

## Acceptance Criteria

- [ ] `LoggingSubscriber` defined and conforms to `EventProvider` Protocol (i.e., `isinstance(LoggingSubscriber(), EventProvider)` is True).
- [ ] `registry.add_provider(LoggingSubscriber())` returns one subscription ID.
- [ ] After registration, emitting any `LifecycleEvent` subclass produces exactly one log record at the configured level.
- [ ] Log line includes the event class name and the trace_id.
- [ ] Custom `level=logging.DEBUG` and `logger_name="custom.name"` are honored.
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_logging_subscriber.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/logging.py` is clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/events/lifecycle/test_logging_subscriber.py
import logging
import pytest

from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.provider import EventProvider
from parrot.core.events.lifecycle.subscribers.logging import LoggingSubscriber
from parrot.core.events.lifecycle.events import BeforeInvokeEvent, AfterToolCallEvent
from parrot.core.events.lifecycle.trace import TraceContext


class TestLoggingSubscriber:
    def test_protocol_conformance(self):
        assert isinstance(LoggingSubscriber(), EventProvider)

    @pytest.mark.asyncio
    async def test_logs_every_event(self, caplog):
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(LoggingSubscriber(level=logging.INFO))
        with caplog.at_level(logging.INFO, logger="parrot.lifecycle"):
            await reg.emit(BeforeInvokeEvent(trace_context=TraceContext.new_root()))
            await reg.emit(AfterToolCallEvent(trace_context=TraceContext.new_root()))
        events = [r for r in caplog.records if r.name == "parrot.lifecycle"]
        assert len(events) == 2
        assert "BeforeInvokeEvent" in events[0].message
        assert "AfterToolCallEvent" in events[1].message

    @pytest.mark.asyncio
    async def test_custom_level(self, caplog):
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(LoggingSubscriber(level=logging.DEBUG))
        with caplog.at_level(logging.DEBUG, logger="parrot.lifecycle"):
            await reg.emit(BeforeInvokeEvent(trace_context=TraceContext.new_root()))
        assert caplog.records[-1].levelno == logging.DEBUG

    @pytest.mark.asyncio
    async def test_includes_trace_id(self, caplog):
        ctx = TraceContext.new_root()
        reg = EventRegistry(forward_to_global=False)
        reg.add_provider(LoggingSubscriber())
        with caplog.at_level(logging.INFO, logger="parrot.lifecycle"):
            await reg.emit(BeforeInvokeEvent(trace_context=ctx))
        assert ctx.trace_id in caplog.records[-1].message
```

---

## Agent Instructions

1. Read spec §3 Module 9.
2. Confirm TASK-1184 is in `sdd/tasks/completed/`.
3. Implement, run tests, update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-15
**Notes**: LoggingSubscriber implemented as EventProvider, subscribes to LifecycleEvent base. 7/7 tests pass. Ruff clean.

**Deviations from spec**: none
