---
type: Wiki Overview
title: 'TASK-1227: Patch EventRegistry.emit for fire-and-forget bus dispatch'
id: doc:sdd-tasks-completed-task-1227-patch-eventregistry-fire-and-forget-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 TASK-000 and §1 Goals — the per-subscriber `forward_to_bus=True`
  branch in `EventRegistry.emit` currently uses blocking `await self._event_bus.emit(...)`.
  A slow Redis bus will block the agent's request path, which makes the §5 performance
  budget (< 0.1% LLM-latency overh
relates_to:
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1227: Patch EventRegistry.emit for fire-and-forget bus dispatch

**Feature**: FEAT-177 — OpenTelemetry + Cost Observability
**Spec**: `sdd/specs/otel-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 TASK-000 and §1 Goals — the per-subscriber `forward_to_bus=True` branch in `EventRegistry.emit` currently uses blocking `await self._event_bus.emit(...)`. A slow Redis bus will block the agent's request path, which makes the §5 performance budget (< 0.1% LLM-latency overhead) unenforceable.

This patch wraps that emit in `asyncio.create_task(...)` so bus forwarding becomes fire-and-forget. It is the foundational task and blocks every other FEAT-177 task.

The brainstorm §2.1 explicitly anticipated this exact patch as the contingency if FEAT-176 didn't ship fire-and-forget. The 2026-05-18 audit confirmed FEAT-176 shipped blocking.

---

## Scope

- Modify `EventRegistry.emit` so the per-subscriber bus forward dispatches via `asyncio.create_task(...)`.
- Catch synchronous scheduling errors (e.g., no running loop) without propagating to callers — log and continue.
- Add two unit tests: one proving non-blocking behavior under a slow bus, one proving exception isolation when the bus task fails.

**NOT in scope**: changing the per-subscriber dispatch contract (callbacks remain `await sub.callback(event)`); changing `_emit_meta` recursion guard; touching `EventBus` itself; touching FEAT-176's `OpenTelemetrySubscriber` stub.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py` | MODIFY | Lines 276-281: wrap bus emit in `asyncio.create_task`. |
| `packages/ai-parrot/tests/unit/core/events/lifecycle/test_registry_fire_and_forget.py` | CREATE | Two tests as described in spec §4 Unit Tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already imported in registry.py — do not re-add:
import asyncio                                                # registry.py:28
import logging                                                # registry.py:30
from parrot.core.events.lifecycle.base import LifecycleEvent  # registry.py:36

# For the test file:
import asyncio
import pytest
from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.events import BeforeInvokeEvent
from parrot.core.events.lifecycle.trace import TraceContext
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py
class EventRegistry:
    async def emit(self, event: LifecycleEvent) -> None: ...     # line 246
    # Current code at lines 276-281 (BLOCKING — to be patched):
    #     if sub.forward_to_bus and self._event_bus is not None:
    #         channel = f"{self._bus_channel_prefix}.{cls_name}"
    #         try:
    #             await self._event_bus.emit(channel, event.to_dict())
    #         except Exception:
    #             logger.exception("Dual-emit to EventBus failed for channel %s", channel)
    #
    # _event_bus is the optional EventBus instance — has signature:
    #     async def emit(self, channel: str, payload: dict) -> None
    #
    # logger module-level: logger = logging.getLogger("parrot.core.events.lifecycle.registry")  # line 56
```

### Does NOT Exist

- ~~`asyncio.ensure_future(...)` as a substitute~~ — use `asyncio.create_task` (the codebase pattern; `_emit_subscriber_error` at line 319 uses the same idiom).
- ~~A `forward_to_bus_blocking` flag~~ — there is no such opt-out and we are not adding one. Bus forwarding is always fire-and-forget after this patch.

---

## Implementation Notes

### Pattern to Follow

The same idiom is already used in `_emit_subscriber_error` (`registry.py:319` per the docstring): "Uses `asyncio.create_task` so the meta-event dispatch does not block the current emit loop." Mirror that pattern.

Replace the block at lines 276-281 with:

```python
if sub.forward_to_bus and self._event_bus is not None:
    channel = f"{self._bus_channel_prefix}.{cls_name}"
    try:
        # Fire-and-forget: a slow bus must never block the agent request path.
        asyncio.create_task(self._event_bus.emit(channel, event.to_dict()))
    except RuntimeError:
        # No running loop at scheduling time — log and continue.
        logger.exception("Dual-emit scheduling failed for channel %s", channel)
```

Use `RuntimeError` (the exception `asyncio.create_task` raises when no loop is running) rather than `except Exception` — bare `Exception` here would hide programming bugs we want surfaced.

The async exception inside `_event_bus.emit` is logged by the running event loop's task-result handler; we do not need to attach an explicit `add_done_callback` for logging (asyncio already logs unhandled task exceptions). Keep the patch minimal.

### Key Constraints

- Do NOT change the per-subscriber callback dispatch (`await sub.callback(event)` at line 266 stays as-is).
- Do NOT touch `_emit_meta` or the recursion-guard ContextVar.
- The patch is one localized edit — no refactors.

### References in Codebase

- `packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py:314-340` — `_emit_subscriber_error` already uses `asyncio.create_task` for fire-and-forget meta dispatch. Mirror.

---

## Acceptance Criteria

- [ ] `EventRegistry.emit` per-subscriber bus branch uses `asyncio.create_task(self._event_bus.emit(...))`.
- [ ] `test_emit_bus_dispatch_is_fire_and_forget` passes — a bus whose `emit` blocks on an `asyncio.Event` does NOT delay `EventRegistry.emit` past a 100 ms wall-clock budget.
- [ ] `test_emit_bus_exception_does_not_break_emit` passes — bus task that raises does not propagate to the `emit` caller; agent flow uninterrupted.
- [ ] No regressions in existing `tests/unit/core/events/lifecycle/` suite.
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/core/events/lifecycle/test_registry_fire_and_forget.py
import asyncio
import pytest
from parrot.core.events.lifecycle.registry import EventRegistry
from parrot.core.events.lifecycle.events import BeforeInvokeEvent
from parrot.core.events.lifecycle.trace import TraceContext


class _SlowBus:
    """Fake EventBus whose emit blocks until released."""
    def __init__(self):
        self.gate = asyncio.Event()
        self.called = 0

    async def emit(self, channel: str, payload: dict) -> None:
        self.called += 1
        await self.gate.wait()


class _FailingBus:
    """Fake EventBus whose emit raises."""
    async def emit(self, channel: str, payload: dict) -> None:
        raise RuntimeError("simulated bus failure")


@pytest.mark.asyncio
async def test_emit_bus_dispatch_is_fire_and_forget():
    bus = _SlowBus()
    reg = EventRegistry(forward_to_global=False, event_bus=bus)

    async def subscriber(_evt):
        pass

    reg.subscribe(BeforeInvokeEvent, subscriber, forward_to_bus=True)

    event = BeforeInvokeEvent(
        trace_context=TraceContext.new_root(),
        agent_name="test", method="ask",
    )
    # If bus dispatch were blocking, this would deadlock on bus.gate.
    await asyncio.wait_for(reg.emit(event), timeout=0.1)
    assert bus.called == 1  # task scheduled (await happened) but not awaited inline
    bus.gate.set()
    await asyncio.sleep(0)  # let the scheduled task drain


@pytest.mark.asyncio
async def test_emit_bus_exception_does_not_break_emit(caplog):
    bus = _FailingBus()
    reg = EventRegistry(forward_to_global=False, event_bus=bus)

    async def subscriber(_evt):
        pass

    reg.subscribe(BeforeInvokeEvent, subscriber, forward_to_bus=True)
    event = BeforeInvokeEvent(
        trace_context=TraceContext.new_root(),
        agent_name="test", method="ask",
    )
    await reg.emit(event)
    # asyncio's default task-exception handler logs unhandled exceptions.
    # Let the failing task run to completion.
    await asyncio.sleep(0)
```

Adjust constructor kwargs (`event_bus=`) and the `subscribe(...)` signature to match the actual `EventRegistry` API — verify against `registry.py` before running.

---

## Agent Instructions

1. Read the spec §3 TASK-000 and §6 Codebase Contract for full context.
2. `read` `registry.py` lines 240-310 to confirm current state still matches this task's contract.
3. Make the one-line patch + add the test file.
4. Run `pytest packages/ai-parrot/tests/unit/core/events/lifecycle/ -v`.
5. Verify no regressions in the broader FEAT-176 suite.

---

## Completion Note

Implemented by sdd-worker on 2026-05-19. The blocking `await self._event_bus.emit(...)` at registry.py lines 276-281 was replaced with `asyncio.create_task(...)`. The `except RuntimeError` guard handles "no running loop at scheduling time". Tests confirm a slow bus does not delay `EventRegistry.emit` past 100ms, and a failing bus task does not propagate to the emit caller. Both unit tests pass with correct PYTHONPATH.
