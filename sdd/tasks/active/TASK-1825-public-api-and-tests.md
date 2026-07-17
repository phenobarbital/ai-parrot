# TASK-1825: Curate public API and complete test suite migration

**Feature**: FEAT-313 — EventBus Lifecycle Extraction (navigator-eventbus phase 2)
**Spec**: `sdd/specs/eventbus-lifecycle-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1822, TASK-1823, TASK-1824
**Assigned-to**: unassigned

---

## Context

This is Module 6 — the final integration task. It curates the `__init__.py`
public API for `navigator_eventbus.lifecycle`, ensuring it exports ONLY the
machinery (no typed events), and completes the test suite with integration
tests: dual-emit to bus, overhead benchmark, and the public API exports test.

It also wires the new `lifecycle` subpackage into the top-level
`navigator_eventbus/__init__.py` exports.

---

## Scope

- Curate `src/navigator_eventbus/lifecycle/__init__.py` with machinery-only exports:
  `TraceContext`, `LifecycleEvent`, `SubscriberErrorEvent`, `EventRegistry`,
  `AsyncSubscriber`, `get_global_registry`, `scope`, `EventProvider`,
  `EventEmitterMixin`, `set_bootstrap_hook`, `wire_events`, `register_event_names`,
  `LoggingSubscriber`, `WebhookSubscriber`.
- Update `src/navigator_eventbus/__init__.py` to re-export key lifecycle symbols.
- Write integration test: `EventRegistry` dual-emit to phase-1 `EventBus` facade.
- Write overhead benchmark: re-run FEAT-177 budget check (< 0.1%).
- Write public API exports test: verify `__init__` exports machinery, absent typed events.
- Ensure the full test suite passes (`pytest tests/ -v`).
- Run `ruff check` and `mypy` across the entire `lifecycle/` subpackage.

**NOT in scope**: typed events (BeforeInvokeEvent, etc.), OpenTelemetrySubscriber, legacy_bridge — all stay in ai-parrot.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/lifecycle/__init__.py` | MODIFY | Curate public API exports |
| `src/navigator_eventbus/__init__.py` | MODIFY | Add lifecycle re-exports |
| `tests/lifecycle/test_public_api.py` | CREATE | Verify exports, absent typed events |
| `tests/lifecycle/test_dual_emit_integration.py` | CREATE | Registry → EventBus end-to-end |
| `tests/lifecycle/test_emit_overhead.py` | CREATE | FEAT-177 overhead budget < 0.1% |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# All modules created by prior tasks — verified at task creation time:
from navigator_eventbus.lifecycle.trace import TraceContext
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.meta import SubscriberErrorEvent
from navigator_eventbus.lifecycle.registry import EventRegistry, AsyncSubscriber
from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope
from navigator_eventbus.lifecycle.provider import EventProvider
from navigator_eventbus.lifecycle.mixin import EventEmitterMixin, set_bootstrap_hook
from navigator_eventbus.lifecycle.yaml_loader import wire_events, register_event_names
from navigator_eventbus.lifecycle.subscribers import LoggingSubscriber, WebhookSubscriber

# Phase-1 facade (for dual-emit integration test):
from navigator_eventbus.evb import EventBus    # verified: src/navigator_eventbus/evb.py
from navigator_eventbus import EventEnvelope   # verified: src/navigator_eventbus/__init__.py
```

### Existing Signatures to Use

```python
# ai-parrot lifecycle/__init__.py exports (reference for what we INCLUDE vs EXCLUDE):
# INCLUDE (machinery):
#   TraceContext, LifecycleEvent, SubscriberErrorEvent, EventRegistry,
#   AsyncSubscriber, get_global_registry, scope, EventProvider,
#   EventEmitterMixin, LoggingSubscriber, WebhookSubscriber
# PLUS (new in this extraction):
#   set_bootstrap_hook, wire_events, register_event_names

# EXCLUDE (typed events — stay in ai-parrot):
#   AgentInitializedEvent, AgentConfiguredEvent, ToolManagerReadyEvent,
#   AgentStatusChangedEvent, BeforeInvokeEvent, AfterInvokeEvent,
#   InvokeFailedEvent, BeforeClientCallEvent, AfterClientCallEvent,
#   ClientCallFailedEvent, ClientStreamChunkEvent, BeforeToolCallEvent,
#   AfterToolCallEvent, ToolCallFailedEvent, MessageAddedEvent,
#   FlowStartedEvent, FlowCompletedEvent, NodeStartedEvent,
#   NodeCompletedEvent, NodeFailedEvent, NodeSkippedEvent

# EXCLUDE (stays in ai-parrot):
#   OpenTelemetrySubscriber

# Phase-1 EventBus dual-emit interface (duck-typed):
# EventRegistry.emit() → asyncio.create_task(bus.emit(channel, payload))
# bus.emit(event_type: str, payload: dict, **kwargs) -> int
```

### Does NOT Exist

- ~~Typed events in the package~~ — `BeforeInvokeEvent`, `AfterInvokeEvent`, etc. are NOT in the package and MUST NOT appear in `__init__.py`.
- ~~`OpenTelemetrySubscriber` in the package~~ — stays in ai-parrot.
- ~~`legacy_bridge` in the package~~ — stays in ai-parrot.
- ~~Existing integration tests for lifecycle in navigator-eventbus~~ — this task creates them.

---

## Implementation Notes

### Pattern to Follow

```python
# src/navigator_eventbus/lifecycle/__init__.py
"""Lifecycle Events Machinery — typed, frozen, observability-first events.

Extracted from ai-parrot's parrot.core.events.lifecycle (FEAT-313).
This package contains ONLY the machinery (registry, mixin, providers,
generic subscribers). Typed agent events (BeforeInvokeEvent, etc.)
remain in ai-parrot and subclass LifecycleEvent from this package.
"""
from navigator_eventbus.lifecycle.trace import TraceContext
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.meta import SubscriberErrorEvent
from navigator_eventbus.lifecycle.registry import EventRegistry, AsyncSubscriber
from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope
from navigator_eventbus.lifecycle.provider import EventProvider
from navigator_eventbus.lifecycle.mixin import EventEmitterMixin, set_bootstrap_hook
from navigator_eventbus.lifecycle.yaml_loader import wire_events, register_event_names
from navigator_eventbus.lifecycle.subscribers import LoggingSubscriber, WebhookSubscriber

__all__ = [
    "TraceContext",
    "LifecycleEvent",
    "SubscriberErrorEvent",
    "EventRegistry",
    "AsyncSubscriber",
    "get_global_registry",
    "scope",
    "EventProvider",
    "EventEmitterMixin",
    "set_bootstrap_hook",
    "wire_events",
    "register_event_names",
    "LoggingSubscriber",
    "WebhookSubscriber",
]
```

### Key Constraints
- The `__init__.py` MUST NOT import any typed events.
- The overhead benchmark must measure emit latency with and without a subscriber and verify < 0.1% overhead on dual-emit (FEAT-177 budget).
- Integration test for dual-emit: create an `EventRegistry` with a phase-1 `EventBus`, emit a lifecycle event, verify the envelope arrives on topic `lifecycle.<ClassName>`.
- Update the top-level `src/navigator_eventbus/__init__.py` to include lifecycle exports (at minimum, add `lifecycle` as an accessible subpackage).

### References in Codebase
- `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py` — reference for export structure
- `src/navigator_eventbus/__init__.py` — top-level package to update
- `src/navigator_eventbus/evb.py` — EventBus facade for integration test

---

## Acceptance Criteria

- [ ] `from navigator_eventbus.lifecycle import EventRegistry, LifecycleEvent, TraceContext, EventEmitterMixin, EventProvider, get_global_registry, scope, LoggingSubscriber, WebhookSubscriber` works (spec AC #1)
- [ ] No `parrot.*` import anywhere under `src/navigator_eventbus/lifecycle/`: `grep -r "from parrot\|import parrot" src/navigator_eventbus/lifecycle/` → 0 hits (spec AC #2)
- [ ] Typed events (`BeforeInvokeEvent`, etc.) are NOT in the package (spec AC #7)
- [ ] `OpenTelemetrySubscriber` is NOT in the package
- [ ] `set_bootstrap_hook` and `register_event_names` are accessible from `navigator_eventbus.lifecycle`
- [ ] Dual-emit integration: EventRegistry → EventBus envelope arrives on `lifecycle.<Class>` topic
- [ ] Overhead benchmark < 0.1% (FEAT-177 budget)
- [ ] All tests pass: `pytest tests/ -v` (entire suite, not just lifecycle)
- [ ] No linting errors: `ruff check src/navigator_eventbus/lifecycle/`
- [ ] Type checking: `mypy src/navigator_eventbus/lifecycle/` passes (or documents known exclusions)

---

## Test Specification

```python
# tests/lifecycle/test_public_api.py
from navigator_eventbus import lifecycle

EXPECTED_EXPORTS = {
    "TraceContext", "LifecycleEvent", "SubscriberErrorEvent",
    "EventRegistry", "AsyncSubscriber", "get_global_registry", "scope",
    "EventProvider", "EventEmitterMixin", "set_bootstrap_hook",
    "wire_events", "register_event_names",
    "LoggingSubscriber", "WebhookSubscriber",
}

MUST_NOT_EXIST = {
    "BeforeInvokeEvent", "AfterInvokeEvent", "InvokeFailedEvent",
    "BeforeClientCallEvent", "AfterClientCallEvent", "ClientCallFailedEvent",
    "ClientStreamChunkEvent", "BeforeToolCallEvent", "AfterToolCallEvent",
    "ToolCallFailedEvent", "MessageAddedEvent", "AgentInitializedEvent",
    "AgentConfiguredEvent", "ToolManagerReadyEvent", "AgentStatusChangedEvent",
    "OpenTelemetrySubscriber",
}

class TestPublicAPI:
    def test_expected_exports_present(self):
        actual = set(lifecycle.__all__)
        assert EXPECTED_EXPORTS.issubset(actual), f"Missing: {EXPECTED_EXPORTS - actual}"

    def test_typed_events_absent(self):
        actual = set(lifecycle.__all__)
        overlap = MUST_NOT_EXIST & actual
        assert not overlap, f"Typed events leaked into package: {overlap}"


# tests/lifecycle/test_dual_emit_integration.py
import pytest
import asyncio
from dataclasses import dataclass
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.trace import TraceContext
from navigator_eventbus.lifecycle.registry import EventRegistry
from navigator_eventbus.evb import EventBus

@dataclass(frozen=True)
class _IntegrationEvent(LifecycleEvent):
    detail: str = ""

class TestDualEmitIntegration:
    @pytest.mark.asyncio
    async def test_emit_forwards_to_bus(self):
        bus = EventBus()
        received = []
        bus.on("lifecycle.*", lambda envelope: received.append(envelope))
        await bus.connect()

        registry = EventRegistry(event_bus=bus, forward_to_global=False)
        evt = _IntegrationEvent(
            trace_context=TraceContext.new_root(),
            source_type="test", source_name="integration", detail="hello"
        )
        await registry.emit(evt)
        await asyncio.sleep(0.1)  # let fire-and-forget task complete

        await bus.close()
        assert len(received) >= 1


# tests/lifecycle/test_emit_overhead.py
import pytest
import time
import asyncio
from dataclasses import dataclass
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.trace import TraceContext
from navigator_eventbus.lifecycle.registry import EventRegistry

@dataclass(frozen=True)
class _BenchEvent(LifecycleEvent):
    detail: str = ""

class TestEmitOverhead:
    @pytest.mark.asyncio
    async def test_overhead_under_budget(self):
        """FEAT-177 budget: < 0.1% overhead on dual-emit path."""
        registry = EventRegistry(forward_to_global=False)
        N = 1000
        evt = _BenchEvent(
            trace_context=TraceContext.new_root(),
            source_type="bench", source_name="overhead"
        )

        # Baseline: no subscribers
        t0 = time.perf_counter()
        for _ in range(N):
            await registry.emit(evt)
        baseline = time.perf_counter() - t0

        # With subscriber
        registry.subscribe(_BenchEvent, lambda e: None)
        t0 = time.perf_counter()
        for _ in range(N):
            await registry.emit(evt)
        with_sub = time.perf_counter() - t0

        # Overhead check — generous margin for CI variance
        if baseline > 0:
            overhead = (with_sub - baseline) / baseline
            assert overhead < 0.1, f"Overhead {overhead:.2%} exceeds 10% (generous CI margin for 0.1% target)"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/eventbus-lifecycle-extraction.spec.md` §2 Module 6
2. **Check dependencies** — verify TASK-1822, TASK-1823, TASK-1824 are all done
3. **Verify the Codebase Contract** — confirm all lifecycle modules exist in the package
4. **Work in the navigator-eventbus repo** at `/home/jesuslara/proyectos/navigator-eventbus`
5. **Curate __init__.py** — machinery only, NO typed events
6. **Run full test suite**: `pytest tests/ -v`
7. **Run lint**: `ruff check src/navigator_eventbus/`
8. **Commit**: `feat: lifecycle public API + integration tests (FEAT-313 TASK-1825)`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
