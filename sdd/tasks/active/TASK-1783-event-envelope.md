# TASK-1783: EventEnvelope, Severity, IngressEnvelope and legacy converters

**Feature**: FEAT-310 — Unified EventBus v2 — queue-based dispatch, severity, ingress channels, and notifications
**Spec**: `sdd/specs/eventbus-v2.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 1 of FEAT-310 (spec §3, Phase 1) — the foundation every other module
builds on. ai-parrot has three incompatible event envelopes (`Event`,
`LifecycleEvent`, `HookEvent`). This task creates the single closed contract
`EventEnvelope` plus the `Severity` enum and converters from all three legacy
shapes. Spec §2 "Data Models" defines the exact shape.

---

## Scope

- Create package `packages/ai-parrot/src/parrot/core/events/bus/` (`__init__.py`).
- Implement `envelope.py`:
  - `Severity(IntEnum)`: DEBUG=10, INFO=20, WARNING=30, ERROR=40, CRITICAL=50.
  - `EventEnvelope` — `@dataclass(frozen=True, slots=True)` with fields:
    `topic: str`, `payload: dict[str, Any]`, `event_id: str` (default uuid4),
    `timestamp: datetime` (MUST be tz-aware; naive → `ValueError` in
    `__post_init__`), `source: str | None`, `severity: Severity` (default INFO),
    `priority: EventPriority` (reuse existing enum), `correlation_id: str | None`,
    `trace_context: dict | None`, `metadata: dict[str, Any]`.
  - `to_dict()` / `from_dict()` round-trip (JSON-safe, for transport backends).
- Implement `ingress_models.py`: `IngressEnvelope(BaseModel)` with
  `model_config = ConfigDict(extra="forbid", frozen=True)` validating external
  input, plus `to_envelope() -> EventEnvelope`.
- Implement `converters.py`: `from_legacy_event(Event)`,
  `from_lifecycle_dict(dict)` (output of `LifecycleEvent.to_dict()`),
  `from_hook_event(HookEvent)` → all return `EventEnvelope`. Naive timestamps
  from legacy sources are coerced to UTC (documented), never rejected.
- Unit tests (spec §4): `test_envelope_rejects_naive_timestamp`,
  `test_envelope_frozen_and_slots`, `test_converters_lifecycle_hookevent_legacy`.

**NOT in scope**: BusCore/queues (TASK-1784), backends (TASK-1785), facade
changes to `evb.py` (TASK-1786), any subscriber.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/bus/__init__.py` | CREATE | package init, export `Severity`, `EventEnvelope`, `IngressEnvelope` |
| `packages/ai-parrot/src/parrot/core/events/bus/envelope.py` | CREATE | `Severity`, `EventEnvelope` (frozen dataclass) |
| `packages/ai-parrot/src/parrot/core/events/bus/ingress_models.py` | CREATE | Pydantic `IngressEnvelope` boundary model |
| `packages/ai-parrot/src/parrot/core/events/bus/converters.py` | CREATE | converters from `Event` / lifecycle dict / `HookEvent` |
| `packages/ai-parrot/tests/core/events/bus/test_envelope.py` | CREATE | unit tests |
| `packages/ai-parrot/tests/core/events/bus/__init__.py` | CREATE | empty test package init (if pattern used elsewhere) |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` 2026-07-16 (commit b7226186d).

### Verified Imports
```python
from parrot.core.events.evb import Event, EventPriority          # evb.py:24, evb.py:15
from parrot.core.hooks.models import HookEvent                   # models.py:31
from pydantic import BaseModel, ConfigDict, Field                # pydantic v2 in use project-wide
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/core/events/evb.py:15
class EventPriority(Enum):
    LOW = 0; NORMAL = 5; HIGH = 10; CRITICAL = 15

# packages/ai-parrot/src/parrot/core/events/evb.py:24 — MUTABLE dataclass, naive datetime.now() at line 29
@dataclass
class Event:
    event_type: str; payload: Dict[str, Any]; event_id: str
    timestamp: datetime; source: Optional[str]; priority: EventPriority
    correlation_id: Optional[str]; metadata: Dict[str, Any]
    def to_dict(self) -> Dict[str, Any]      # line 35
    @classmethod
    def from_dict(cls, data) -> "Event"      # line 48

# packages/ai-parrot/src/parrot/core/events/lifecycle/base.py:21
@dataclass(frozen=True)
class LifecycleEvent(ABC):
    trace_context: TraceContext; event_id: str
    timestamp: datetime                       # tz-aware (timezone.utc)
    source_type: str; source_name: str
    def to_dict(self) -> dict[str, Any]       # line 52 — adds "event_class" hint

# packages/ai-parrot/src/parrot/core/hooks/models.py:31
class HookEvent(BaseModel):
    hook_id: str; hook_type: HookType; event_type: str
    payload: Dict[str, Any]; metadata: Dict[str, Any]
    timestamp: datetime                       # default_factory=datetime.now — NAIVE, must coerce to UTC
    target_type: Optional[str]; target_id: Optional[str]; task: Optional[str]
```

### Does NOT Exist
- ~~`parrot/core/events/bus/` package~~ — created by THIS task.
- ~~`Severity` enum anywhere in core/events~~ — created here; `EventPriority` is scheduling, NOT severity.
- ~~`LifecycleEvent` direct import into converters~~ — convert from its **dict form** (`to_dict()` output) to avoid importing the lifecycle ABC into the bus package; the dict contains an `"event_class"` key.
- ~~`pydantic.v1` shims~~ — project is Pydantic v2 native.

---

## Implementation Notes

### Pattern to Follow
Frozen-dataclass style mirrors `LifecycleEvent` (`lifecycle/base.py:21`) —
FEAT-176 measured ~5x faster instantiation than Pydantic on hot paths.
Pydantic (`extra="forbid"`, `frozen=True`) ONLY at the ingress boundary
(*resolved in brainstorm*).

### Key Constraints
- `EventEnvelope.__post_init__` raises `ValueError` on naive `timestamp`.
- Converters COERCE naive legacy timestamps to UTC (legacy `Event`/`HookEvent`
  use naive `datetime.now()`); only direct construction rejects naive.
- `slots=True` + `frozen=True` — no `__dict__`; tests assert both.
- Google-style docstrings, strict type hints, no blocking I/O (pure data module).

### References in Codebase
- `packages/ai-parrot/src/parrot/core/events/lifecycle/base.py` — frozen dataclass + tz-aware pattern
- `packages/ai-parrot/src/parrot/core/hooks/models.py` — Pydantic model conventions

---

## Acceptance Criteria

- [ ] `from parrot.core.events.bus import Severity, EventEnvelope, IngressEnvelope` works.
- [ ] Naive `timestamp` on direct construction raises `ValueError`; converters coerce to UTC.
- [ ] Envelope is frozen (`FrozenInstanceError` on assignment) and slotted (no `__dict__`).
- [ ] Three converter paths produce semantically identical envelopes for equivalent inputs.
- [ ] `to_dict()`/`from_dict()` round-trips (severity/priority as values, ISO timestamp).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/core/events/bus/test_envelope.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/core/events/bus/`

---

## Test Specification

```python
# packages/ai-parrot/tests/core/events/bus/test_envelope.py
import pytest
from datetime import datetime, timezone
from parrot.core.events.bus import EventEnvelope, Severity
from parrot.core.events.bus.converters import (
    from_legacy_event, from_lifecycle_dict, from_hook_event,
)
from parrot.core.events.evb import Event, EventPriority
from parrot.core.hooks.models import HookEvent, HookType


def test_envelope_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="tz-aware"):
        EventEnvelope(topic="a.b", payload={}, timestamp=datetime.now())


def test_envelope_frozen_and_slots():
    env = EventEnvelope(topic="a.b", payload={},
                        timestamp=datetime.now(timezone.utc))
    with pytest.raises(Exception):
        env.topic = "other"
    assert not hasattr(env, "__dict__")


def test_converters_lifecycle_hookevent_legacy():
    legacy = Event(event_type="x.y", payload={"k": 1})
    hook = HookEvent(hook_id="h1", hook_type=HookType.WEBHOOK,
                     event_type="jira.issue", payload={})
    for env in (from_legacy_event(legacy), from_hook_event(hook)):
        assert env.timestamp.tzinfo is not None
        assert env.severity == Severity.INFO
```

---

## Agent Instructions

1. Read the spec §2 (Data Models) and §6 before writing code.
2. Verify every import in the contract still resolves (`grep`/`read`).
3. Implement per scope; do NOT touch `evb.py` or any file outside the list.
4. Update `sdd/tasks/index/eventbus-v2.json` → `in-progress`, then `done`.
5. Move this file to `sdd/tasks/completed/` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
