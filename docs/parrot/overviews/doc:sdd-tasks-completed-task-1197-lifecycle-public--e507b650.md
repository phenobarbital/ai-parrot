---
type: Wiki Overview
title: 'TASK-1197: Curate public API exports for lifecycle events package'
id: doc:sdd-tasks-completed-task-1197-lifecycle-public-exports-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 17 of the spec. Curate the public API of `parrot.core.events.lifecycle`
  so users have one clean import statement for all common types. Without this, users
  would import from `parrot.core.events.lifecycle.events.invoke`, `parrot.core.events.lifecycle.registry`,
  etc. — too ve
relates_to:
- concept: mod:parrot.core.events.lifecycle
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events.invoke
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.legacy_bridge
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.meta
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.mixin
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.provider
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.subscribers.logging
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.subscribers.opentelemetry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.subscribers.webhook
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1197: Curate public API exports for lifecycle events package

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-1186, TASK-1187, TASK-1188, TASK-1189, TASK-1184, TASK-1190, TASK-1191, TASK-1192, TASK-1182
**Assigned-to**: unassigned

---

## Context

Module 17 of the spec. Curate the public API of `parrot.core.events.lifecycle` so users have one clean import statement for all common types. Without this, users would import from `parrot.core.events.lifecycle.events.invoke`, `parrot.core.events.lifecycle.registry`, etc. — too verbose.

Spec section: §3 Module 17.

---

## Scope

- Populate `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py` with re-exports.
- Use `__all__` to declare the public surface explicitly.
- Public symbols:
  - **Trace**: `TraceContext`
  - **Base**: `LifecycleEvent`
  - **All concrete events**: 15 classes (re-exported from `events.*`)
  - **Meta**: `SubscriberErrorEvent`
  - **Registry**: `EventRegistry`, `AsyncSubscriber` (type alias)
  - **Global**: `get_global_registry`, `scope`
  - **Provider**: `EventProvider`
  - **Mixin**: `EventEmitterMixin`
  - **Subscribers**: `LoggingSubscriber`, `OpenTelemetrySubscriber`, `WebhookSubscriber` (the OTel one re-exports the class — the `ImportError` only fires on instantiation, so importing the symbol always works).
- Verify `from parrot.core.events.lifecycle import *` produces a usable namespace.
- Add a one-line test importing every public symbol.

**NOT in scope**: docs (TASK-1199), PoC script (TASK-1198), benchmarks (TASK-1200).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py` | MODIFY (overwrite from empty marker created in TASK-1182) | Public API curation. |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_public_api.py` | CREATE | Import-everything smoke test. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (already in this package after prior tasks)

```python
from parrot.core.events.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.base import LifecycleEvent
from parrot.core.events.lifecycle.meta import SubscriberErrorEvent
from parrot.core.events.lifecycle.registry import EventRegistry, AsyncSubscriber
from parrot.core.events.lifecycle.global_registry import get_global_registry, scope
from parrot.core.events.lifecycle.provider import EventProvider
from parrot.core.events.lifecycle.mixin import EventEmitterMixin
from parrot.core.events.lifecycle.events import (
    AgentInitializedEvent, AgentConfiguredEvent,
    ToolManagerReadyEvent, AgentStatusChangedEvent,
    BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,
    BeforeClientCallEvent, AfterClientCallEvent,
    ClientCallFailedEvent, ClientStreamChunkEvent,
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,
    MessageAddedEvent,
)
from parrot.core.events.lifecycle.subscribers.logging import LoggingSubscriber
from parrot.core.events.lifecycle.subscribers.opentelemetry import OpenTelemetrySubscriber
from parrot.core.events.lifecycle.subscribers.webhook import WebhookSubscriber
```

### Does NOT Exist

- ~~`parrot.core.events.lifecycle.legacy_bridge` as a public export~~ — `_LegacyEventBridge` is private (underscore prefix). Do NOT re-export.
- ~~Wildcard imports inside `__init__.py`~~ — explicit re-exports only for clarity.

---

## Implementation Notes

### `__init__.py` shape

```python
"""Lifecycle Events System — typed, frozen, observability-first events.

FEAT-176. See `packages/ai-parrot/docs/lifecycle_events.md` for the
user guide.
"""

from parrot.core.events.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.base import LifecycleEvent
from parrot.core.events.lifecycle.meta import SubscriberErrorEvent
from parrot.core.events.lifecycle.registry import EventRegistry, AsyncSubscriber
from parrot.core.events.lifecycle.global_registry import get_global_registry, scope
from parrot.core.events.lifecycle.provider import EventProvider
from parrot.core.events.lifecycle.mixin import EventEmitterMixin

# Concrete events
from parrot.core.events.lifecycle.events import (
    AgentInitializedEvent, AgentConfiguredEvent,
    ToolManagerReadyEvent, AgentStatusChangedEvent,
    BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,
    BeforeClientCallEvent, AfterClientCallEvent,
    ClientCallFailedEvent, ClientStreamChunkEvent,
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,
    MessageAddedEvent,
)

# Built-in subscribers
from parrot.core.events.lifecycle.subscribers.logging import LoggingSubscriber
from parrot.core.events.lifecycle.subscribers.opentelemetry import OpenTelemetrySubscriber
from parrot.core.events.lifecycle.subscribers.webhook import WebhookSubscriber


__all__ = [
    # Trace
    "TraceContext",
    # Base
    "LifecycleEvent", "SubscriberErrorEvent",
    # Concrete events
    "AgentInitializedEvent", "AgentConfiguredEvent",
    "ToolManagerReadyEvent", "AgentStatusChangedEvent",
    "BeforeInvokeEvent", "AfterInvokeEvent", "InvokeFailedEvent",
    "BeforeClientCallEvent", "AfterClientCallEvent",
    "ClientCallFailedEvent", "ClientStreamChunkEvent",
    "BeforeToolCallEvent", "AfterToolCallEvent", "ToolCallFailedEvent",
    "MessageAddedEvent",
    # Registry + dispatch
    "EventRegistry", "AsyncSubscriber",
    "get_global_registry", "scope",
    # Provider + mixin
    "EventProvider", "EventEmitterMixin",
    # Built-in subscribers
    "LoggingSubscriber", "OpenTelemetrySubscriber", "WebhookSubscriber",
]
```

### Why we re-export `OpenTelemetrySubscriber` even though its deps are optional

The class import always succeeds (lazy imports live inside `__init__`). Users importing the symbol can later instantiate and get the clear `ImportError` message at construction time. This keeps the public API stable regardless of whether the `otel` extra is installed.

### Smoke test

```python
# packages/ai-parrot/tests/unit/events/lifecycle/test_public_api.py
def test_public_api_imports():
    import parrot.core.events.lifecycle as ll
    for name in [
        "TraceContext", "LifecycleEvent", "SubscriberErrorEvent",
        "EventRegistry", "AsyncSubscriber",
        "get_global_registry", "scope",
        "EventProvider", "EventEmitterMixin",
        "LoggingSubscriber", "OpenTelemetrySubscriber", "WebhookSubscriber",
        "BeforeInvokeEvent", "AfterInvokeEvent", "InvokeFailedEvent",
        "BeforeClientCallEvent", "AfterClientCallEvent",
        "ClientCallFailedEvent", "ClientStreamChunkEvent",
        "BeforeToolCallEvent", "AfterToolCallEvent", "ToolCallFailedEvent",
        "AgentInitializedEvent", "AgentConfiguredEvent",
        "ToolManagerReadyEvent", "AgentStatusChangedEvent",
        "MessageAddedEvent",
    ]:
        assert hasattr(ll, name), f"Missing public symbol: {name}"
```

### Circular import sanity check

Before finishing the task, run:

```bash
python -c "from parrot.core.events.lifecycle import *; print('ok')"
```

Must print `ok` with no `ImportError`.

---

## Acceptance Criteria

- [ ] `from parrot.core.events.lifecycle import *` exposes all symbols in `__all__`.
- [ ] Every name in `__all__` actually exists in the namespace.
- [ ] Import the module without the `otel` extra installed still works (`OpenTelemetrySubscriber` is importable but uninstantiable).
- [ ] Smoke test passes: `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_public_api.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py` is clean.

---

## Test Specification

(See Smoke test above.)

---

## Agent Instructions

1. Confirm all dependency tasks are in `sdd/tasks/completed/`.
2. Apply the `__init__.py`, run the smoke test.
3. Verify the bare-import command (`python -c "..."`) succeeds.
4. Update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-15
**Notes**:
- lifecycle/__init__.py populated with all 28 public symbols across TraceContext, LifecycleEvent, SubscriberErrorEvent, 15 concrete event classes, EventRegistry, AsyncSubscriber, get_global_registry, scope, EventProvider, EventEmitterMixin, LoggingSubscriber, OpenTelemetrySubscriber, WebhookSubscriber
- __all__ declared explicitly
- Smoke test (3 tests) verifies all symbols accessible, __all__ integrity, and wildcard import
- `from parrot.core.events.lifecycle import *` prints 'ok' cleanly

**Deviations from spec**: none
