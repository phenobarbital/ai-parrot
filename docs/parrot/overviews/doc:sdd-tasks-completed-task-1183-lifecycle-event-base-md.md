---
type: Wiki Overview
title: 'TASK-1183: Implement LifecycleEvent base class'
id: doc:sdd-tasks-completed-task-1183-lifecycle-event-base-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 2 of the spec. `LifecycleEvent` is the abstract frozen dataclass that
  every concrete lifecycle event inherits from. It carries the cross-cutting fields
  (`trace_context`, `event_id`, `timestamp`, `source_type`, `source_name`) and implements
  `to_dict()` with strict JSON vali
relates_to:
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1183: Implement LifecycleEvent base class

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-1182
**Assigned-to**: unassigned

---

## Context

Module 2 of the spec. `LifecycleEvent` is the abstract frozen dataclass that every concrete lifecycle event inherits from. It carries the cross-cutting fields (`trace_context`, `event_id`, `timestamp`, `source_type`, `source_name`) and implements `to_dict()` with strict JSON validation — a key acceptance criterion (non-JSON-serializable fields must raise `TypeError`).

Spec section: §2 Data Models → `parrot/core/events/lifecycle/base.py`.

---

## Scope

- Implement the `LifecycleEvent` abstract frozen dataclass with the five required fields.
- Implement `to_dict()` that returns a JSON-compatible dict AND validates JSON-serializability by calling `json.dumps` internally; raises `TypeError` naming the offending field.
- Add unit tests covering: frozen mutation raises, to_dict roundtrips through json.dumps, non-JSON field raises a clear `TypeError`.

**NOT in scope**: concrete event classes (TASK-1184), `SubscriberErrorEvent` (TASK-1184), registry (TASK-1186).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/base.py` | CREATE | `LifecycleEvent` ABC + frozen dataclass + `to_dict()`. |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_base.py` | CREATE | Unit tests for `LifecycleEvent`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from abc import ABC
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from typing import Any
import json
import uuid

from parrot.core.events.lifecycle.trace import TraceContext   # from TASK-1182
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/trace.py — created in TASK-1182
@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    trace_flags: int = 0
    trace_state: str = ""
    parent_span_id: Optional[str] = None
    def to_dict(self) -> dict: ...
```

### Does NOT Exist

- ~~`LifecycleEvent` anywhere else in the codebase~~ — being created now.
- ~~`pydantic.BaseModel` parent~~ — events are `@dataclass(frozen=True)`, NEVER Pydantic (spec §7 Patterns to Follow).
- ~~`navconfig.events.*`~~ — does not exist.

---

## Implementation Notes

### Required field order (matters because subclasses add defaulted fields after)

```python
@dataclass(frozen=True)
class LifecycleEvent(ABC):
    trace_context: TraceContext
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_type: str = ""    # "agent" | "client" | "tool"
    source_name: str = ""
```

Note: `trace_context` has no default because it's a required identity field — every event MUST be tagged with a trace. Subclasses inherit this and add their own defaulted fields after.

### `to_dict()` — strict JSON validation

```python
def to_dict(self) -> dict[str, Any]:
    if not is_dataclass(self):
        raise TypeError(f"{type(self).__name__} is not a dataclass")
    out: dict[str, Any] = {}
    for f in fields(self):
        value = getattr(self, f.name)
        if isinstance(value, TraceContext):
            value = value.to_dict()
        elif isinstance(value, datetime):
            value = value.isoformat()
        out[f.name] = value
    out["event_class"] = type(self).__name__   # for cross-process deserialization hints
    try:
        json.dumps(out)
    except TypeError as exc:
        raise TypeError(
            f"{type(self).__name__}.to_dict() produced a non-JSON-serializable value: {exc}"
        ) from exc
    return out
```

Tuple fields (e.g., `ToolManagerReadyEvent.tool_names: tuple[str, ...]`) serialize fine because `json.dumps` converts tuples to arrays — but `to_dict()` should convert tuple values to list explicitly before the json check, to keep round-trips clean. (Implementer's call — the explicit `list(value) if isinstance(value, tuple) else value` is fine.)

### Key Constraints

- `@dataclass(frozen=True)` — mandatory.
- `ABC` parent — this base is not directly instantiated; concrete subclasses are.
- No subscribers, no registry — pure data class.
- Don't use `dataclasses.asdict` — it deep-copies and won't run our strict JSON check.

---

## Acceptance Criteria

- [ ] `parrot/core/events/lifecycle/base.py` exists with `LifecycleEvent` dataclass.
- [ ] `from parrot.core.events.lifecycle.base import LifecycleEvent` works.
- [ ] Mutating a `LifecycleEvent` instance raises `FrozenInstanceError`.
- [ ] `event.to_dict()` returns a dict that round-trips through `json.dumps`.
- [ ] A subclass with a non-JSON-serializable field (e.g., an open file handle) raises `TypeError` from `to_dict()`.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_base.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/base.py` is clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/events/lifecycle/test_base.py
import json
import pytest
from dataclasses import dataclass, FrozenInstanceError

from parrot.core.events.lifecycle.base import LifecycleEvent
from parrot.core.events.lifecycle.trace import TraceContext


@dataclass(frozen=True)
class _DummyEvent(LifecycleEvent):
    payload: str = ""


@dataclass(frozen=True)
class _BadEvent(LifecycleEvent):
    open_file: object = None    # non-JSON


class TestLifecycleEvent:
    def test_frozen(self):
        evt = _DummyEvent(trace_context=TraceContext.new_root())
        with pytest.raises(FrozenInstanceError):
            evt.payload = "x"   # type: ignore[misc]

    def test_to_dict_roundtrips_json(self):
        evt = _DummyEvent(trace_context=TraceContext.new_root(), payload="hello")
        assert json.dumps(evt.to_dict())

    def test_to_dict_includes_event_class(self):
        evt = _DummyEvent(trace_context=TraceContext.new_root())
        assert evt.to_dict()["event_class"] == "_DummyEvent"

    def test_non_json_field_raises_typeerror(self, tmp_path):
        fh = open(tmp_path / "x.txt", "w")
        try:
            evt = _BadEvent(trace_context=TraceContext.new_root(), open_file=fh)
            with pytest.raises(TypeError, match="non-JSON-serializable"):
                evt.to_dict()
        finally:
            fh.close()
```

---

## Agent Instructions

1. Read the spec at the path above for full context.
2. Confirm TASK-1182 is in `sdd/tasks/completed/`.
3. Implement, run tests, update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
