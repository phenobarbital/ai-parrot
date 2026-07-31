---
type: Wiki Overview
title: 'TASK-1188: Implement EventProvider Protocol'
id: doc:sdd-tasks-completed-task-1188-event-provider-protocol-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 7 of the spec. `EventProvider` is a `runtime_checkable` Protocol that
  lets users bundle multiple subscriber callbacks under a single registerable object
  (e.g., `OpenTelemetrySubscriber` registers subscribers for `BeforeInvokeEvent`,
  `AfterInvokeEvent`, and `InvokeFailedEve
relates_to:
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.provider
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
---

# TASK-1188: Implement EventProvider Protocol

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S
**Depends-on**: TASK-1186
**Assigned-to**: unassigned

---

## Context

Module 7 of the spec. `EventProvider` is a `runtime_checkable` Protocol that lets users bundle multiple subscriber callbacks under a single registerable object (e.g., `OpenTelemetrySubscriber` registers subscribers for `BeforeInvokeEvent`, `AfterInvokeEvent`, and `InvokeFailedEvent` in one call). `EventRegistry.add_provider(provider)` invokes `provider.register(self)` and returns the list of subscription IDs.

Spec section: §2 New Public Interfaces (lines 429–450) and §3 Module 7.

**Parallel-safe** with TASK-1187 (different file).

---

## Scope

- Implement `EventProvider` as `typing.Protocol` decorated with `@runtime_checkable`.
- Add `EventRegistry.add_provider()` integration. Since `EventRegistry` already exists from TASK-1186, this task adds the method body (TASK-1186 left it as a method-stub with a lazy import; this task fills it in with the actual collection logic).
- Add unit tests covering: provider registers multiple callbacks; returned subscription IDs match the ones returned by `subscribe()`; `add_provider` raises `TypeError` if the object doesn't conform.

**NOT in scope**: actual provider implementations (`OpenTelemetrySubscriber`, `WebhookSubscriber` — TASK-1191, TASK-1192).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/provider.py` | CREATE | `EventProvider` Protocol. |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py` | MODIFY | Fill in `add_provider()` body with subscription collection. |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_provider.py` | CREATE | Provider conformance + registration tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Protocol, runtime_checkable

from parrot.core.events.lifecycle.registry import EventRegistry   # TASK-1186
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py — from TASK-1186
class EventRegistry:
    def subscribe(
        self,
        event_type: Type[E],
        callback: AsyncSubscriber,
        *,
        where: Optional[Callable[[E], bool]] = None,
        forward_to_bus: bool = False,
    ) -> str: ...

    def add_provider(self, provider: "EventProvider") -> list[str]: ...
```

### Does NOT Exist

- ~~`AbstractEventProvider` (abstract class)~~ — we use `typing.Protocol`, not ABC.
- ~~`@event_provider` decorator~~ — none. Conformance is structural via Protocol.

---

## Implementation Notes

### `EventProvider` Protocol

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/provider.py
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from parrot.core.events.lifecycle.registry import EventRegistry


@runtime_checkable
class EventProvider(Protocol):
    """Bundles multiple callbacks for batch registration with an EventRegistry.

    Example:
        class TelemetryProvider:
            def register(self, registry: "EventRegistry") -> None:
                registry.subscribe(BeforeInvokeEvent, self.on_invoke_start)
                registry.subscribe(AfterInvokeEvent, self.on_invoke_end)
    """
    def register(self, registry: "EventRegistry") -> None: ...
```

### `EventRegistry.add_provider` body

```python
def add_provider(self, provider) -> list[str]:
    # Lazy import to avoid circular dependency.
    from parrot.core.events.lifecycle.provider import EventProvider

    if not isinstance(provider, EventProvider):
        raise TypeError(
            f"{type(provider).__name__} is not an EventProvider "
            "(missing register(registry) method)."
        )
    before = list(self._subscriptions_by_id.keys())   # internal attribute name TBC
    provider.register(self)
    after = list(self._subscriptions_by_id.keys())
    return [sid for sid in after if sid not in before]
```

The diff-of-subscription-ids approach works regardless of how the provider chooses to call `subscribe()`. If TASK-1186 used a different internal data structure, adapt the diff approach accordingly (e.g., wrap `subscribe()` in a counter for the duration of `register()`).

### Why `runtime_checkable`

`isinstance(obj, EventProvider)` works without inheritance — any object with a `register(self, registry)` method conforms. This keeps the API duck-typed and friendly to user-defined classes.

### Key Constraints

- Protocol must be `@runtime_checkable` so `isinstance` works.
- `register()` MUST be sync (registration happens at agent setup time, before any event loop work).
- `add_provider()` returns the list of subscription IDs created during the call — caller can use them for batch unsubscribe.

---

## Acceptance Criteria

- [ ] `EventProvider` Protocol defined and `@runtime_checkable`.
- [ ] `from parrot.core.events.lifecycle.provider import EventProvider` works.
- [ ] `EventRegistry.add_provider(provider)` returns the list of subscription IDs created.
- [ ] Calling `add_provider` with a non-conforming object raises `TypeError`.
- [ ] `isinstance(obj_with_register_method, EventProvider)` is `True`.
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_provider.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/provider.py packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py` is clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/events/lifecycle/test_provider.py
import pytest

from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.provider import EventProvider
from parrot.core.events.lifecycle.events import (
    BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,
)


class _GoodProvider:
    def __init__(self):
        self.calls = []

    def register(self, registry):
        async def on_start(e): self.calls.append("start")
        async def on_end(e): self.calls.append("end")
        registry.subscribe(BeforeInvokeEvent, on_start)
        registry.subscribe(AfterInvokeEvent, on_end)


class _BadProvider:
    pass   # no .register method


class TestEventProvider:
    def test_conformance_check(self):
        assert isinstance(_GoodProvider(), EventProvider)
        assert not isinstance(_BadProvider(), EventProvider)

    def test_add_provider_returns_ids(self):
        reg = EventRegistry(forward_to_global=False)
        ids = reg.add_provider(_GoodProvider())
        assert len(ids) == 2
        assert all(isinstance(sid, str) for sid in ids)

    def test_add_provider_rejects_non_conforming(self):
        reg = EventRegistry(forward_to_global=False)
        with pytest.raises(TypeError, match="not an EventProvider"):
            reg.add_provider(_BadProvider())
```

---

## Agent Instructions

1. Read spec §2 lines 429–450 and §3 Module 7.
2. Open `parrot/core/events/lifecycle/registry.py` (from TASK-1186) and locate the `add_provider` method stub.
3. Implement the Protocol in a new file, fill in the registry method.
4. Run tests, update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-15
**Notes**: EventProvider Protocol implemented with @runtime_checkable. add_provider() updated to use diff-of-subscription-IDs approach (before_ids set vs after). 9/9 tests pass. Ruff clean. No deviations.

**Deviations from spec**: none
