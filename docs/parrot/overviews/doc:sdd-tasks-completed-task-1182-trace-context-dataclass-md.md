---
type: Wiki Overview
title: 'TASK-1182: Implement TraceContext dataclass'
id: doc:sdd-tasks-completed-task-1182-trace-context-dataclass-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Module 1 of the spec. `TraceContext` is the W3C Trace Context dataclass
  that propagates trace identity across agent → client → tool → sub-agent boundaries.
  It is the foundation for every other module in this feature: events embed it, `PermissionContext`
  carries it, `EventEmitterM'
relates_to:
- concept: mod:parrot.core.events.lifecycle
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1182: Implement TraceContext dataclass

**Feature**: FEAT-176 — Lifecycle Events System
**Spec**: `sdd/specs/FEAT-176-lifecycle-events-system.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of the spec. `TraceContext` is the W3C Trace Context dataclass that propagates trace identity across agent → client → tool → sub-agent boundaries. It is the foundation for every other module in this feature: events embed it, `PermissionContext` carries it, `EventEmitterMixin` creates child contexts, and `OpenTelemetrySubscriber` maps it to spans.

Spec section: §2 Data Models → `parrot/core/events/lifecycle/trace.py`.

---

## Scope

- Create the directory `packages/ai-parrot/src/parrot/core/events/lifecycle/` with an empty `__init__.py` so it is a package (the public-export curation happens in TASK-1197).
- Implement the `TraceContext` frozen dataclass with the fields and methods declared in the spec.
- Implement `new_root()`, `child()`, `from_traceparent_header()`, `to_traceparent_header()`, `to_dict()`, `from_dict()`.
- Add unit tests covering: root creation, child preserves trace_id + new span_id + parent_span_id wiring, traceparent header round-trip, invalid header raises `ValueError`.

**NOT in scope**: `LifecycleEvent` base (TASK-1183), `PermissionContext` extension (TASK-1185), any subscribers, any OpenTelemetry imports.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py` | CREATE | Empty package marker (public exports added later in TASK-1197). |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/trace.py` | CREATE | `TraceContext` dataclass + helpers. |
| `packages/ai-parrot/tests/unit/events/lifecycle/__init__.py` | CREATE | Test package marker. |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_trace_context.py` | CREATE | Unit tests for `TraceContext`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# stdlib only — no project imports needed for this task
from dataclasses import dataclass, field
from typing import Optional
import secrets   # for trace_id / span_id generation
```

### Existing Signatures to Use

None — this module has zero dependencies on existing project code. Use stdlib `secrets.token_hex(16)` for trace_id (32 hex chars) and `secrets.token_hex(8)` for span_id (16 hex chars).

### Does NOT Exist

- ~~`parrot.core.events.lifecycle.*`~~ — entire package being created in this task.
- ~~`TraceContext` anywhere in the codebase~~ — verified absent in the spec preparation phase.
- ~~`opentelemetry.*`~~ — must NOT be imported here (lazy in TASK-1191 only).

---

## Implementation Notes

### W3C traceparent header format

```
00-<trace_id:32hex>-<span_id:16hex>-<trace_flags:2hex>
```

- Version is always `00` for this implementation.
- Reject headers that don't match this exact shape with `ValueError`.
- `trace_state` is the optional `tracestate` header (vendor extension list). Keep as string; do not parse.

### `new_root()`

```python
@classmethod
def new_root(cls) -> "TraceContext":
    return cls(
        trace_id=secrets.token_hex(16),
        span_id=secrets.token_hex(8),
        trace_flags=1,                   # sampled=true by default
        trace_state="",
        parent_span_id=None,
    )
```

### `child()`

Returns a new `TraceContext` with:
- same `trace_id`, `trace_flags`, `trace_state`
- fresh `span_id` via `secrets.token_hex(8)`
- `parent_span_id` set to the current `span_id`

### `to_dict()` / `from_dict()`

Plain dict with all five fields. `to_dict()` must round-trip through `json.dumps`.

### Key Constraints

- `@dataclass(frozen=True)` — mutation must raise `FrozenInstanceError`.
- All fields type-annotated.
- No `print` — use `navconfig.logging` if logging is needed (not expected for this small module).

---

## Acceptance Criteria

- [ ] `parrot/core/events/lifecycle/trace.py` exists with `TraceContext` dataclass.
- [ ] `from parrot.core.events.lifecycle.trace import TraceContext` works.
- [ ] `TraceContext.new_root()` returns a valid instance (32-char trace_id, 16-char span_id, parent_span_id=None).
- [ ] `ctx.child()` preserves `trace_id`, mints a new `span_id`, and wires `parent_span_id` to the parent's `span_id`.
- [ ] `TraceContext.from_traceparent_header(ctx.to_traceparent_header())` reproduces `ctx`.
- [ ] Invalid traceparent (wrong version, wrong length, wrong hex) raises `ValueError`.
- [ ] Mutation raises `FrozenInstanceError`.
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_trace_context.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/core/events/lifecycle/trace.py` is clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/events/lifecycle/test_trace_context.py
import json
import pytest
from dataclasses import FrozenInstanceError

from parrot.core.events.lifecycle.trace import TraceContext


class TestTraceContext:
    def test_new_root_format(self):
        ctx = TraceContext.new_root()
        assert len(ctx.trace_id) == 32 and all(c in "0123456789abcdef" for c in ctx.trace_id)
        assert len(ctx.span_id) == 16 and all(c in "0123456789abcdef" for c in ctx.span_id)
        assert ctx.parent_span_id is None

    def test_child_preserves_trace_id(self):
        root = TraceContext.new_root()
        child = root.child()
        assert child.trace_id == root.trace_id
        assert child.span_id != root.span_id
        assert child.parent_span_id == root.span_id

    def test_traceparent_roundtrip(self):
        ctx = TraceContext.new_root()
        header = ctx.to_traceparent_header()
        restored = TraceContext.from_traceparent_header(header)
        assert restored.trace_id == ctx.trace_id
        assert restored.span_id == ctx.span_id
        assert restored.trace_flags == ctx.trace_flags

    @pytest.mark.parametrize("bad", [
        "",
        "00-tooshort-1234567890abcdef-01",
        "01-" + "a" * 32 + "-" + "b" * 16 + "-01",  # wrong version
        "not-a-header",
    ])
    def test_invalid_traceparent_raises(self, bad):
        with pytest.raises(ValueError):
            TraceContext.from_traceparent_header(bad)

    def test_frozen(self):
        ctx = TraceContext.new_root()
        with pytest.raises(FrozenInstanceError):
            ctx.trace_id = "deadbeef" * 4  # type: ignore[misc]

    def test_to_dict_is_json_serializable(self):
        ctx = TraceContext.new_root()
        assert json.dumps(ctx.to_dict())
```

---

## Agent Instructions

1. Read the spec at the path above for full context.
2. Verify `packages/ai-parrot/src/parrot/core/events/` exists (it does — contains `evb.py`). Create the `lifecycle/` subdirectory.
3. Confirm `secrets` is the right RNG (it is — `secrets.token_hex` is cryptographically strong; `uuid.uuid4().hex` would also work but `secrets` is more idiomatic for opaque identifiers).
4. Implement, run tests, update the per-spec index, move this file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
