---
type: Wiki Overview
title: 'TASK-1184: Implement concrete lifecycle event classes'
id: doc:sdd-tasks-completed-task-1184-concrete-lifecycle-events-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Modules 3 + 4 of the spec. This task creates all 15 concrete lifecycle event
  classes (agent / invoke / client / tool / message domains) plus the `SubscriberErrorEvent`
  meta-event used by the error-isolation model. Every event is `@dataclass(frozen=True)`
  and inherits from `Lifecy
relates_to:
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.meta
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1184: Implement concrete lifecycle event classes

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-1183
**Assigned-to**: unassigned

---

## Context

Modules 3 + 4 of the spec. This task creates all 15 concrete lifecycle event classes (agent / invoke / client / tool / message domains) plus the `SubscriberErrorEvent` meta-event used by the error-isolation model. Every event is `@dataclass(frozen=True)` and inherits from `LifecycleEvent`.

Spec section: §2 Data Models → `parrot/core/events/lifecycle/events/*.py` and `parrot/core/events/lifecycle/meta.py`.

---

## Scope

- Create five submodule files under `parrot/core/events/lifecycle/events/`:
  - `agent.py` → `AgentInitializedEvent`, `AgentConfiguredEvent`, `ToolManagerReadyEvent`, `AgentStatusChangedEvent`
  - `invoke.py` → `BeforeInvokeEvent`, `AfterInvokeEvent`, `InvokeFailedEvent`
  - `client.py` → `BeforeClientCallEvent`, `AfterClientCallEvent`, `ClientCallFailedEvent`, `ClientStreamChunkEvent`
  - `tool.py` → `BeforeToolCallEvent`, `AfterToolCallEvent`, `ToolCallFailedEvent`
  - `message.py` → `MessageAddedEvent`
- Create `parrot/core/events/lifecycle/meta.py` with `SubscriberErrorEvent`.
- Create `parrot/core/events/lifecycle/events/__init__.py` re-exporting all event classes for convenience.
- Add unit tests verifying each class is frozen, instantiates with required fields, and `to_dict()` is JSON-serializable.

**NOT in scope**: registry, mixin, subscribers, integration into AbstractBot/Client/Tool.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/__init__.py` | CREATE | Re-export every concrete event class. |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/agent.py` | CREATE | 4 agent-lifecycle dataclasses. |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/invoke.py` | CREATE | 3 invocation-lifecycle dataclasses. |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` | CREATE | 4 client-lifecycle dataclasses. |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py` | CREATE | 3 tool-lifecycle dataclasses. |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/message.py` | CREATE | `MessageAddedEvent`. |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/meta.py` | CREATE | `SubscriberErrorEvent`. |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_concrete_events.py` | CREATE | Frozen + to_dict tests for every class. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from dataclasses import dataclass, field
from typing import Optional

from parrot.core.events.lifecycle.base import LifecycleEvent   # from TASK-1183
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/base.py — from TASK-1183
@dataclass(frozen=True)
class LifecycleEvent(ABC):
    trace_context: TraceContext
    event_id: str
    timestamp: datetime
    source_type: str = ""
    source_name: str = ""
    def to_dict(self) -> dict[str, Any]: ...
```

### Does NOT Exist

- ~~Pydantic models for events~~ — frozen dataclasses only.
- ~~`BeforeCrewExecutionEvent`, `NodeHandoffEvent`~~ — Phase 1.5, NOT in this task.
- ~~`event.cancel()` / `event.retry`~~ — interceptor concerns (Phase 2), NOT here.

---

## Implementation Notes

### Exact field shapes — copy from spec §2 verbatim

Spec lines 207–334 define every field for every class. Reproduce them exactly. Notable subtleties:

- **`AgentStatusChangedEvent.old_status` / `.new_status`** are strings holding the `AgentStatus.name` (uppercase: `"IDLE"`, `"WORKING"`, `"COMPLETED"`, `"FAILED"`). Verified enum in `packages/ai-parrot/src/parrot/models/status.py`.
- **`ToolManagerReadyEvent.tool_names`** is `tuple[str, ...]` (immutable). Convert to list inside `to_dict()` if needed (handled by base class with explicit tuple→list conversion if you added it in TASK-1183).
- **`BeforeClientCallEvent.system_prompt_hash`** is SHA-256 hex of the prompt — NEVER the prompt itself. The hashing happens at the emission site (TASK-1194), not here. The dataclass just holds the string.
- **`BeforeToolCallEvent.args_summary`** is `dict` (truncation happens at the emission site in TASK-1195).
- **`ClientStreamChunkEvent`** carries `chunk_index` and `chunk_size_bytes` only — never the chunk text itself. This is intentional for performance and PII safety.
- **`SubscriberErrorEvent`** lives in `meta.py`, NOT `events/`, because it is meta (emitted only by the registry, not by domain code).

### Field defaults

All fields except `trace_context` (inherited) must have defaults, because `LifecycleEvent` has defaulted fields and Python disallows non-default fields after default ones. Use `""`, `0`, `0.0`, `False`, `None`, `()`, `dict` factory, etc. as appropriate.

### `__init__.py` re-exports

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/events/__init__.py
from .agent import (
    AgentInitializedEvent, AgentConfiguredEvent,
    ToolManagerReadyEvent, AgentStatusChangedEvent,
)
from .invoke import BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent
from .client import (
    BeforeClientCallEvent, AfterClientCallEvent,
    ClientCallFailedEvent, ClientStreamChunkEvent,
)
from .tool import BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent
from .message import MessageAddedEvent

__all__ = [
    "AgentInitializedEvent", "AgentConfiguredEvent",
    "ToolManagerReadyEvent", "AgentStatusChangedEvent",
    "BeforeInvokeEvent", "AfterInvokeEvent", "InvokeFailedEvent",
    "BeforeClientCallEvent", "AfterClientCallEvent",
    "ClientCallFailedEvent", "ClientStreamChunkEvent",
    "BeforeToolCallEvent", "AfterToolCallEvent", "ToolCallFailedEvent",
    "MessageAddedEvent",
]
```

`SubscriberErrorEvent` lives in `meta.py` and is exported by the top-level `lifecycle/__init__.py` (TASK-1197), not from `events/__init__.py`.

---

## Acceptance Criteria

- [ ] All 15 concrete event classes implemented per spec §2.
- [ ] `SubscriberErrorEvent` implemented in `meta.py`.
- [ ] Every class is `@dataclass(frozen=True)` — mutation raises `FrozenInstanceError`.
- [ ] Every class instantiates with only `trace_context=...` (all other fields have defaults).
- [ ] `to_dict()` (inherited) returns JSON-serializable dicts for every class.
- [ ] `from parrot.core.events.lifecycle.events import BeforeInvokeEvent` works (and similarly for all 15).
- [ ] `from parrot.core.events.lifecycle.meta import SubscriberErrorEvent` works.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_concrete_events.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/events/ packages/ai-parrot/src/parrot/core/events/lifecycle/meta.py` is clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/events/lifecycle/test_concrete_events.py
import json
import pytest
from dataclasses import FrozenInstanceError

from parrot.core.events.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.events import (
    AgentInitializedEvent, AgentConfiguredEvent,
    ToolManagerReadyEvent, AgentStatusChangedEvent,
    BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,
    BeforeClientCallEvent, AfterClientCallEvent,
    ClientCallFailedEvent, ClientStreamChunkEvent,
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,
    MessageAddedEvent,
)
from parrot.core.events.lifecycle.meta import SubscriberErrorEvent


ALL_CLASSES = [
    AgentInitializedEvent, AgentConfiguredEvent,
    ToolManagerReadyEvent, AgentStatusChangedEvent,
    BeforeInvokeEvent, AfterInvokeEvent, InvokeFailedEvent,
    BeforeClientCallEvent, AfterClientCallEvent,
    ClientCallFailedEvent, ClientStreamChunkEvent,
    BeforeToolCallEvent, AfterToolCallEvent, ToolCallFailedEvent,
    MessageAddedEvent, SubscriberErrorEvent,
]


@pytest.fixture
def trace_root():
    return TraceContext.new_root()


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_instantiate_with_defaults(cls, trace_root):
    evt = cls(trace_context=trace_root)
    assert evt.trace_context is trace_root


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_frozen(cls, trace_root):
    evt = cls(trace_context=trace_root)
    with pytest.raises(FrozenInstanceError):
        evt.source_name = "x"   # type: ignore[misc]


@pytest.mark.parametrize("cls", ALL_CLASSES)
def test_to_dict_json_serializable(cls, trace_root):
    evt = cls(trace_context=trace_root)
    assert json.dumps(evt.to_dict())


def test_tool_manager_ready_tuple_field(trace_root):
    evt = ToolManagerReadyEvent(
        trace_context=trace_root, tool_count=2, tool_names=("a", "b"),
    )
    assert evt.tool_names == ("a", "b")
    assert json.dumps(evt.to_dict())
```

---

## Agent Instructions

1. Read the spec at the path above for full context.
2. Confirm TASK-1183 is in `sdd/tasks/completed/` and `LifecycleEvent` is importable.
3. Implement each event file, run tests, update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
