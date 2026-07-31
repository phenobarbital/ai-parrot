---
type: Wiki Overview
title: 'TASK-1233: ParrotTelemetryProvider (EventProvider bundle)'
id: doc:sdd-tasks-completed-task-1233-parrot-telemetry-provider-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 6. Implements FEAT-176's `EventProvider` Protocol. Bundles
  the trace subscriber, metrics subscriber, and cost calculator into a single object
  that `setup_telemetry` registers via `get_global_registry().add_provider(...)`.
relates_to:
- concept: mod:parrot.core.events.lifecycle.provider
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
- concept: mod:parrot.observability
  rel: mentions
- concept: mod:parrot.observability.subscribers.metrics
  rel: mentions
- concept: mod:parrot.observability.subscribers.trace
  rel: mentions
---

# TASK-1233: ParrotTelemetryProvider (EventProvider bundle)

**Feature**: FEAT-177 — OpenTelemetry + Cost Observability
**Spec**: `sdd/specs/otel-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1230, TASK-1231, TASK-1232
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6. Implements FEAT-176's `EventProvider` Protocol. Bundles the trace subscriber, metrics subscriber, and cost calculator into a single object that `setup_telemetry` registers via `get_global_registry().add_provider(...)`.

---

## Scope

- Create `parrot/observability/provider.py` with `ParrotTelemetryProvider`.
- Constructor accepts the three subscribers (already-built) — no business logic of its own.
- `register(registry)` calls each subscriber's `register(registry)` in turn.
- Unit test that `add_provider` registers all expected subscriptions.

**NOT in scope**: building the subscribers themselves (that's TASK-1230 / TASK-1231 / TASK-1232); calling `add_provider` (that's TASK-1235).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/observability/provider.py` | CREATE | `ParrotTelemetryProvider`. |
| `packages/ai-parrot/src/parrot/observability/__init__.py` | MODIFY | Add `ParrotTelemetryProvider` to public re-exports. |
| `packages/ai-parrot/tests/unit/observability/test_provider.py` | CREATE | Bundling + registration count test. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from parrot.observability.subscribers.trace import GenAIOpenTelemetrySubscriber
from parrot.observability.subscribers.metrics import MetricsSubscriber

if TYPE_CHECKING:
    from parrot.core.events.lifecycle.registry import EventRegistry
```

### Existing Signatures to Use

```python
# parrot/core/events/lifecycle/provider.py:19-51 — EventProvider Protocol
@runtime_checkable
class EventProvider(Protocol):
    def register(self, registry: "EventRegistry") -> None: ...   # line 45 — MUST be synchronous

# Each of our subscribers exposes the same method:
class GenAIOpenTelemetrySubscriber:
    def register(self, registry: "EventRegistry") -> None: ...
class MetricsSubscriber:
    def register(self, registry: "EventRegistry") -> None: ...
```

### Does NOT Exist

- ~~`CostCalculator.register(registry)`~~ — not a subscriber, just a service injected into the other two. Do NOT call `register` on it.

---

## Implementation Notes

```python
class ParrotTelemetryProvider:
    """Bundles trace + metrics subscribers for one-call registration."""

    def __init__(
        self,
        *,
        trace_subscriber: Optional[GenAIOpenTelemetrySubscriber] = None,
        metrics_subscriber: Optional[MetricsSubscriber] = None,
    ) -> None:
        self._trace = trace_subscriber
        self._metrics = metrics_subscriber

    def register(self, registry: "EventRegistry") -> None:
        if self._trace is not None:
            self._trace.register(registry)
        if self._metrics is not None:
            self._metrics.register(registry)
```

Either subscriber may be None (e.g., trace-only or metrics-only deployments). If both are None, `register` is a no-op.

---

## Acceptance Criteria

- [ ] `from parrot.observability import ParrotTelemetryProvider` resolves.
- [ ] `isinstance(ParrotTelemetryProvider(), EventProvider)` is True (Protocol conformance).
- [ ] `register(registry)` invokes each non-None subscriber's `register` exactly once.
- [ ] `ParrotTelemetryProvider()` (both None) is a no-op — no exceptions.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/observability/test_provider.py
from unittest.mock import MagicMock
from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.provider import EventProvider
from parrot.observability import ParrotTelemetryProvider


def test_protocol_conformance():
    assert isinstance(ParrotTelemetryProvider(), EventProvider)


def test_register_invokes_each_subscriber():
    trace = MagicMock()
    metrics = MagicMock()
    p = ParrotTelemetryProvider(trace_subscriber=trace, metrics_subscriber=metrics)
    reg = EventRegistry(forward_to_global=False)
    p.register(reg)
    trace.register.assert_called_once_with(reg)
    metrics.register.assert_called_once_with(reg)


def test_no_op_when_both_none():
    p = ParrotTelemetryProvider()
    reg = EventRegistry(forward_to_global=False)
    p.register(reg)   # must not raise
```

---

## Agent Instructions

1. Confirm TASK-1230, TASK-1231, TASK-1232 complete.
2. Implement provider.py, update `__init__.py` re-exports, add tests.
3. Run `pytest packages/ai-parrot/tests/unit/observability/test_provider.py -v`.

---

## Completion Note

*(Agent fills this in when done)*
