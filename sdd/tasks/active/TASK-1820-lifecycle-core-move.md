# TASK-1820: Move core lifecycle machinery (base, trace, meta)

**Feature**: FEAT-313 — EventBus Lifecycle Extraction (navigator-eventbus phase 2)
**Spec**: `sdd/specs/eventbus-lifecycle-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is Module 1 of the lifecycle extraction. It moves the foundational
dataclasses (`LifecycleEvent`, `TraceContext`, `SubscriberErrorEvent`) from
ai-parrot into the `navigator-eventbus` package at
`src/navigator_eventbus/lifecycle/`. These three modules have zero external
coupling — only intra-package imports that change from `parrot.core.events.lifecycle.*`
to `navigator_eventbus.lifecycle.*`.

All subsequent modules depend on these base classes.

---

## Scope

- Create `src/navigator_eventbus/lifecycle/` package directory with `__init__.py` (empty initially — Module 6 curates it).
- Copy `trace.py` verbatim from ai-parrot `lifecycle/trace.py` (zero deps, no import changes).
- Copy `base.py` from ai-parrot `lifecycle/base.py`, changing only the intra-package import:
  `from parrot.core.events.lifecycle.trace import TraceContext` → `from navigator_eventbus.lifecycle.trace import TraceContext`.
- Copy `meta.py` from ai-parrot `lifecycle/meta.py`, changing only:
  `from parrot.core.events.lifecycle.base import LifecycleEvent` → `from navigator_eventbus.lifecycle.base import LifecycleEvent`.
- Preserve module docstrings and FEAT-176/177 references.
- Write unit tests for the three moved classes.

**NOT in scope**: registry, global_registry, provider, mixin, yaml_loader, subscribers, `__init__.py` public API curation (Module 6).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/lifecycle/__init__.py` | CREATE | Empty package init (curated in TASK-1825) |
| `src/navigator_eventbus/lifecycle/trace.py` | CREATE | TraceContext — verbatim copy, zero deps |
| `src/navigator_eventbus/lifecycle/base.py` | CREATE | LifecycleEvent ABC — import path change only |
| `src/navigator_eventbus/lifecycle/meta.py` | CREATE | SubscriberErrorEvent — import path change only |
| `tests/lifecycle/test_trace_context.py` | CREATE | Unit tests for TraceContext |
| `tests/lifecycle/test_base.py` | CREATE | Unit tests for LifecycleEvent |
| `tests/lifecycle/test_meta.py` | CREATE | Unit tests for SubscriberErrorEvent |
| `tests/lifecycle/__init__.py` | CREATE | Test package init |
| `tests/lifecycle/conftest.py` | CREATE | Shared fixtures for lifecycle tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Source: ai-parrot packages/ai-parrot/src/parrot/core/events/lifecycle/

# trace.py — ZERO external imports (only stdlib)
from dataclasses import dataclass          # trace.py:9
from typing import Optional                # trace.py:10
import secrets                             # trace.py:11

# base.py — one intra-package import
from abc import ABC                        # base.py:10
from dataclasses import dataclass, field, fields  # base.py:11
from datetime import datetime, timezone    # base.py:12
from typing import Any                     # base.py:13
import json                                # base.py:14
import uuid                                # base.py:15
from parrot.core.events.lifecycle.trace import TraceContext  # base.py:17 → CHANGE to navigator_eventbus

# meta.py — one intra-package import
from dataclasses import dataclass          # meta.py:8
from typing import Any                     # meta.py:9
from parrot.core.events.lifecycle.base import LifecycleEvent  # meta.py:11 → CHANGE to navigator_eventbus
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/trace.py:14
@dataclass(frozen=True)
class TraceContext:
    trace_id: str       # 32-hex
    span_id: str        # 16-hex
    parent_span_id: Optional[str] = None
    trace_flags: int = 1
    @classmethod
    def new_root(cls) -> "TraceContext": ...       # :45
    def child(self) -> "TraceContext": ...          # :62
    @classmethod
    def from_traceparent_header(cls, header: str) -> "TraceContext": ...  # :91
    def to_traceparent_header(self) -> str: ...     # :161
    def to_dict(self) -> dict: ...                  # :177
    @classmethod
    def from_dict(cls, data: dict) -> "TraceContext": ...  # :198

# packages/ai-parrot/src/parrot/core/events/lifecycle/base.py:20-21
@dataclass(frozen=True)
class LifecycleEvent(ABC):
    trace_context: TraceContext
    event_id: str       # default factory uuid4
    timestamp: datetime  # tz-aware
    source_type: str
    source_name: str
    def to_dict(self) -> dict[str, Any]: ...  # :52 — strict json validation

# packages/ai-parrot/src/parrot/core/events/lifecycle/meta.py:14-15
@dataclass(frozen=True)
class SubscriberErrorEvent(LifecycleEvent):
    subscriber_name: str = ""
    error_message: str = ""
    original_event_class: str = ""
    original_event_id: str = ""
    traceback: str = ""
    def to_dict(self) -> dict[str, Any]: ...  # :47
```

### Does NOT Exist

- ~~`navigator_eventbus.lifecycle` package~~ — does not exist yet; this task creates it.
- ~~`LifecycleEvent` as a Pydantic model~~ — it is a frozen dataclass, NOT Pydantic (FEAT-176 perf rationale).
- ~~External deps in trace.py~~ — zero; pure stdlib.
- ~~`from navconfig` in base/trace/meta~~ — none of these three modules use navconfig.

---

## Implementation Notes

### Pattern to Follow

Fresh-copy move: copy each file from ai-parrot source, change ONLY intra-package
import paths from `parrot.core.events.lifecycle.*` to `navigator_eventbus.lifecycle.*`.
Preserve all docstrings, comments, and FEAT references verbatim.

### Key Constraints
- Frozen dataclasses MUST stay dataclasses (NOT Pydantic) — hot-path instantiation, ~5x faster.
- `trace.py` has zero external deps — copy verbatim, no changes at all.
- `base.py` has exactly ONE import to change (trace.py path).
- `meta.py` has exactly ONE import to change (base.py path).
- Preserve the `to_dict()` strict json validation logic in base.py (it rejects non-serializable fields).
- `__init__.py` should be minimal/empty — Module 6 (TASK-1825) curates the public API.

### References in Codebase
- `packages/ai-parrot/src/parrot/core/events/lifecycle/trace.py` — copy source (219 LOC)
- `packages/ai-parrot/src/parrot/core/events/lifecycle/base.py` — copy source (98 LOC)
- `packages/ai-parrot/src/parrot/core/events/lifecycle/meta.py` — copy source (65 LOC)

---

## Acceptance Criteria

- [ ] `from navigator_eventbus.lifecycle.trace import TraceContext` works
- [ ] `from navigator_eventbus.lifecycle.base import LifecycleEvent` works
- [ ] `from navigator_eventbus.lifecycle.meta import SubscriberErrorEvent` works
- [ ] No `parrot.*` imports in any of the three files: `grep -r "from parrot\|import parrot" src/navigator_eventbus/lifecycle/{base,trace,meta}.py` → 0 hits
- [ ] `LifecycleEvent` is frozen: mutating a field raises `FrozenInstanceError`
- [ ] `TraceContext.new_root()` → valid traceparent; `.child()` preserves trace_id
- [ ] `TraceContext.from_traceparent_header()` / `.to_traceparent_header()` round-trip
- [ ] `SubscriberErrorEvent` inherits from `LifecycleEvent` and is frozen
- [ ] `to_dict()` on all three classes produces JSON-serializable dicts
- [ ] All tests pass: `pytest tests/lifecycle/ -v`
- [ ] No linting errors: `ruff check src/navigator_eventbus/lifecycle/`

---

## Test Specification

```python
# tests/lifecycle/test_trace_context.py
import pytest
from navigator_eventbus.lifecycle.trace import TraceContext

class TestTraceContext:
    def test_new_root_creates_valid_trace(self):
        tc = TraceContext.new_root()
        assert len(tc.trace_id) == 32
        assert len(tc.span_id) == 16
        assert tc.parent_span_id is None

    def test_child_preserves_trace_id(self):
        root = TraceContext.new_root()
        child = root.child()
        assert child.trace_id == root.trace_id
        assert child.parent_span_id == root.span_id
        assert child.span_id != root.span_id

    def test_traceparent_header_roundtrip(self):
        tc = TraceContext.new_root()
        header = tc.to_traceparent_header()
        restored = TraceContext.from_traceparent_header(header)
        assert restored.trace_id == tc.trace_id
        assert restored.span_id == tc.span_id

    def test_to_dict_from_dict_roundtrip(self):
        tc = TraceContext.new_root()
        d = tc.to_dict()
        restored = TraceContext.from_dict(d)
        assert restored == tc

    def test_frozen(self):
        tc = TraceContext.new_root()
        with pytest.raises(AttributeError):
            tc.trace_id = "mutated"

# tests/lifecycle/test_base.py
import pytest
from navigator_eventbus.lifecycle.base import LifecycleEvent
from navigator_eventbus.lifecycle.trace import TraceContext
from dataclasses import dataclass

@dataclass(frozen=True)
class _SampleEvent(LifecycleEvent):
    detail: str = ""

class TestLifecycleEvent:
    def test_frozen_instance(self):
        evt = _SampleEvent(
            trace_context=TraceContext.new_root(),
            source_type="test", source_name="unit"
        )
        with pytest.raises(AttributeError):
            evt.source_type = "mutated"

    def test_to_dict_json_serializable(self):
        import json
        evt = _SampleEvent(
            trace_context=TraceContext.new_root(),
            source_type="test", source_name="unit", detail="hello"
        )
        d = evt.to_dict()
        json.dumps(d)  # must not raise
        assert d["event_class"] == "_SampleEvent"
        assert d["detail"] == "hello"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no deps; start immediately
3. **Verify the Codebase Contract** — confirm source files at the listed paths still match
4. **Work in the navigator-eventbus repo** at `/home/jesuslara/proyectos/navigator-eventbus`
5. **Copy files** from ai-parrot source, changing only import paths
6. **Run tests**: `pytest tests/lifecycle/ -v`
7. **Run lint**: `ruff check src/navigator_eventbus/lifecycle/`
8. **Commit** with message: `feat: lifecycle core machinery — base, trace, meta (FEAT-313 TASK-1820)`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
