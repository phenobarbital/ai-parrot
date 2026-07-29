---
type: Wiki Overview
title: 'TASK-1401: LedgerRecorder — Global Event Capture'
id: doc:sdd-tasks-completed-task-1401-ledger-recorder-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: with a `where` filter that excludes `config.exclude_event_classes`.
relates_to:
- concept: mod:parrot.autonomous.ledger
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
---

# TASK-1401: LedgerRecorder — Global Event Capture

**Feature**: FEAT-212 — Typed Event Ledger & Crash Resume
**Spec**: `sdd/specs/FEAT-212-event-ledger-resume.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1400
**Assigned-to**: unassigned

---

## Context

> Implements Module 3 of FEAT-212. The `LedgerRecorder` subscribes to the global
> lifecycle event registry and persists every event (except filtered ones like
> `ClientStreamChunkEvent`) into the `EventLedger`. Uses batched async writes to
> avoid blocking the agent hot-path. This is the bridge between the existing
> event system (FEAT-176) and the new persistent ledger.

---

## Scope

- Add `LedgerRecorder` class to `ledger.py`.
- Implement `start()` — subscribes to `get_global_registry()` for `LifecycleEvent`
  with a `where` filter that excludes `config.exclude_event_classes`.
- Implement `stop()` — unsubscribes (using the subscription_id from `start()`).
- Implement `on_event(evt)` — converts `LifecycleEvent` → `LedgerEvent` via
  `from_lifecycle()` and appends to the ledger.
- Implement non-blocking batched writes: internal queue + background flush task
  that drains the queue in batches of `config.batch_size`.
- Write unit tests using `InMemoryLedgerBackend` + mock registry.

**NOT in scope**: resume logic (TASK-1402), wiring/exports (TASK-1403).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/autonomous/ledger.py` | MODIFY | Add LedgerRecorder class |
| `packages/ai-parrot-server/tests/test_ledger_recorder.py` | CREATE | Unit tests for recorder |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Global registry (singleton)
from parrot.core.events.lifecycle.global_registry import get_global_registry  # verified: global_registry.py:37

# EventRegistry subscribe signature
from parrot.core.events.lifecycle.registry import EventRegistry       # verified: registry.py:90

# Base event type
from parrot.core.events.lifecycle.base import LifecycleEvent          # verified: base.py:20-21

# From this module (TASK-1399/1400)
from parrot.autonomous.ledger import EventLedger, LedgerEvent, LedgerConfig

import asyncio
import logging
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/global_registry.py
def get_global_registry() -> EventRegistry: ...   # line 37 (singleton)

# packages/ai-parrot/src/parrot/core/events/lifecycle/registry.py
class EventRegistry:                              # line 90
    def subscribe(
        self,
        event_type: Type[E],
        callback: AsyncSubscriber,          # Callable[[E], Awaitable[None]]
        *,
        where: Optional[Callable[[E], bool]] = None,
        forward_to_bus: bool = False,
    ) -> str: ...                                  # line 121 (returns subscription_id)

    def unsubscribe(self, subscription_id: str) -> bool: ...  # line 159

# LifecycleEvent.to_dict() → dict (line 52-98)
# LedgerEvent.from_lifecycle(evt) → LedgerEvent (from TASK-1399)
```

### Does NOT Exist
- ~~`EventRegistry.on()` or `.listen()`~~ — use `subscribe()` which returns a subscription_id string.
- ~~`get_global_registry().register()`~~ — use `subscribe()` on the returned registry.
- ~~Synchronous callback support~~ — `subscribe` requires `AsyncSubscriber` (async callable).
- ~~`LifecycleEvent.event_type` property~~ — use `type(evt).__name__` to get the class name.

---

## Implementation Notes

### Pattern to Follow
```python
class LedgerRecorder:
    def __init__(self, ledger: EventLedger, *, config: LedgerConfig | None = None) -> None:
        self._ledger = ledger
        self._config = config or LedgerConfig()
        self._subscription_id: Optional[str] = None
        self._queue: asyncio.Queue[LedgerEvent] = asyncio.Queue()
        self._flush_task: Optional[asyncio.Task] = None
        self.logger = logging.getLogger(__name__)

    def start(self) -> None:
        registry = get_global_registry()
        exclude = self._config.exclude_event_classes
        self._subscription_id = registry.subscribe(
            LifecycleEvent,
            self.on_event,
            where=lambda e: type(e).__name__ not in exclude,
        )
        self._flush_task = asyncio.create_task(self._flush_loop())

    def stop(self) -> None:
        if self._subscription_id:
            get_global_registry().unsubscribe(self._subscription_id)
            self._subscription_id = None
        if self._flush_task:
            self._flush_task.cancel()

    async def on_event(self, evt: LifecycleEvent) -> None:
        le = LedgerEvent.from_lifecycle(evt)
        await self._queue.put(le)

    async def _flush_loop(self) -> None:
        """Background task: drain queue in batches."""
        while True:
            batch = []
            # Wait for at least one event
            batch.append(await self._queue.get())
            # Drain up to batch_size - 1 more without waiting
            while len(batch) < self._config.batch_size:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            # Persist batch
            for event in batch:
                try:
                    await self._ledger.append(event)
                except Exception:
                    self.logger.exception("Failed to append ledger event")
```

### Key Constraints
- `on_event` MUST be async (required by `AsyncSubscriber` type).
- The `where` filter prevents `ClientStreamChunkEvent` from reaching `on_event` at all.
- Batched writes: use an internal `asyncio.Queue` + background task to avoid blocking
  the event emission path. The recorder is fire-and-forget from the agent's perspective.
- One `LedgerRecorder` per process (avoid duplicate subscriptions).
- `stop()` must cancel the flush task and unsubscribe.

---

## Acceptance Criteria

- [ ] `LedgerRecorder.start()` subscribes to the global registry for `LifecycleEvent`.
- [ ] `ClientStreamChunkEvent` is NOT persisted (filtered by `where`).
- [ ] Non-excluded events are persisted via `EventLedger.append()`.
- [ ] Writes are non-blocking (async queue + background flush task).
- [ ] `stop()` unsubscribes and cancels the flush task.
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/test_ledger_recorder.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/autonomous/ledger.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_ledger_recorder.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from parrot.core.events.lifecycle.base import TraceContext
from parrot.core.events.lifecycle.events import (
    BeforeToolCallEvent, ClientStreamChunkEvent,
)


@pytest.fixture
def memory_ledger():
    from parrot.autonomous.ledger import InMemoryLedgerBackend
    return InMemoryLedgerBackend()


@pytest.fixture
def recorder(memory_ledger):
    from parrot.autonomous.ledger import LedgerRecorder
    return LedgerRecorder(memory_ledger)


class TestLedgerRecorder:
    @pytest.mark.asyncio
    async def test_recorder_persists_on_emit(self, recorder, memory_ledger):
        """Emitting a lifecycle event through on_event results in an append."""
        tc = TraceContext(trace_id="t-1", span_id="s-1")
        evt = BeforeToolCallEvent(
            trace_context=tc, tool_name="calc", source_type="agent",
        )
        await recorder.on_event(evt)
        # Manually flush
        await asyncio.sleep(0.1)
        events = await memory_ledger.read()
        assert len(events) >= 1
        assert events[0].event_class == "BeforeToolCallEvent"

    @pytest.mark.asyncio
    async def test_recorder_skips_stream_chunks(self, recorder):
        """ClientStreamChunkEvent should be excluded by the where filter."""
        from parrot.autonomous.ledger import LedgerConfig
        cfg = LedgerConfig()
        exclude = cfg.exclude_event_classes
        # Simulate the where filter
        tc = TraceContext(trace_id="t-2", span_id="s-2")
        chunk = ClientStreamChunkEvent(
            trace_context=tc, client_name="openai",
            model="gpt-4", chunk_index=0, chunk_size_bytes=100,
        )
        assert type(chunk).__name__ in exclude  # would be filtered

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(self, recorder):
        """stop() cancels flush task and unsubscribes."""
        with patch("parrot.autonomous.ledger.get_global_registry") as mock_reg:
            mock_registry = MagicMock()
            mock_registry.subscribe.return_value = "sub-123"
            mock_reg.return_value = mock_registry
            recorder.start()
            assert recorder._subscription_id == "sub-123"
            recorder.stop()
            mock_registry.unsubscribe.assert_called_once_with("sub-123")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-212-event-ledger-resume.spec.md` for full context
2. **Check dependencies** — verify TASK-1400 is complete (`EventLedger` + `InMemoryLedgerBackend` exist)
3. **Verify the Codebase Contract** — confirm `get_global_registry`, `subscribe` signature
4. **Update status** in `sdd/tasks/index/event-ledger-resume.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1401-ledger-recorder.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-01
**Notes**: LedgerRecorder was implemented in ledger.py (TASK-1399). Created
test_ledger_recorder.py with 11 tests covering: persistence via on_event with flush loop,
ClientStreamChunkEvent filter via where= predicate, start/stop subscription lifecycle,
and batching behavior. Tests that require the flush loop running now use start()/stop()
with mocked global registry.

**Deviations from spec**: None. All acceptance criteria met.
