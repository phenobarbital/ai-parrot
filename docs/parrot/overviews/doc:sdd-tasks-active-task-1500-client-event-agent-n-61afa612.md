---
type: Wiki Overview
title: 'TASK-1500: Add agent_name field to client lifecycle events'
id: doc:sdd-tasks-active-task-1500-client-event-agent-name-field-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §2 Data Models, §3 Module 2. The agent identity must ride on the client
relates_to:
- concept: mod:parrot.core.events.lifecycle.events.client
  rel: mentions
---

# TASK-1500: Add agent_name field to client lifecycle events

**Feature**: FEAT-228 — Per-Agent Cost & Usage Metrics
**Spec**: `sdd/specs/per-agent-cost-usage-metrics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models, §3 Module 2. The agent identity must ride on the client
lifecycle event so downstream subscribers (metrics + trace) can label by agent
without coupling to the bot. This task adds the optional field; populating it
from the ContextVar is TASK-1502, consuming it is TASK-1503/1504.

---

## Scope

- Add an optional `agent_name: Optional[str] = None` field to the three client
  events in `core/events/lifecycle/events/client.py`:
  `BeforeClientCallEvent`, `AfterClientCallEvent`, `ClientCallFailedEvent`.
- Keep each `@dataclass(frozen=True)`; the new field MUST have a default so
  existing construction sites stay backward compatible.
- Update each class docstring's Attributes section to document `agent_name`.

**NOT in scope**: setting the field (TASK-1502), reading it (TASK-1503/1504),
the ContextVar itself (TASK-1499).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` | MODIFY | Add `agent_name` to the 3 dataclasses + docstrings |
| `packages/ai-parrot/tests/unit/.../test_client_events.py` (or existing event test) | CREATE/MODIFY | Field defaults to None; `to_dict()` JSON check still passes |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py
@dataclass(frozen=True)
class BeforeClientCallEvent(LifecycleEvent):   # line 18
    client_name: str = ""        # line 30
    model: str = ""              # line 31
    temperature: Optional[float] = None  # line 32
    system_prompt_hash: str = ""         # line 33
    has_tools: bool = False              # line 34

@dataclass(frozen=True)
class AfterClientCallEvent(LifecycleEvent):    # line 38
    client_name: str = ""        # line 53
    model: str = ""              # line 54
    duration_ms: float = 0.0     # line 55
    input_tokens: Optional[int] = None   # line 56
    output_tokens: Optional[int] = None
    finish_reason: Optional[str] = None

@dataclass(frozen=True)
class ClientCallFailedEvent(LifecycleEvent):   # line 62
    client_name: str = ""        # line 75
    model: str = ""              # line 76
    duration_ms: float = 0.0     # line 77
    error_type: str = ""         # line 78
    error_message: str = ""      # line 79

# packages/ai-parrot/src/parrot/core/events/lifecycle/base.py
class LifecycleEvent(ABC):   # line 21
    # has trace_context, source_type, source_name, event_id, timestamp.
    # to_dict() runs a strict json.dumps validation — all fields must be
    # JSON-serializable. `agent_name: Optional[str]` is a str/None → OK.
```

### Does NOT Exist
- ~~`AfterClientCallEvent.agent_name`~~ — added by THIS task.
- ~~`chatbot_id` field on any event~~ — out of scope; do NOT add.

---

## Implementation Notes

### Pattern to Follow
```python
@dataclass(frozen=True)
class AfterClientCallEvent(LifecycleEvent):
    client_name: str = ""
    model: str = ""
    duration_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    agent_name: Optional[str] = None   # NEW — invoking agent's self.name (None if unknown)
```

### Key Constraints
- Default `None` is mandatory (frozen dataclass field ordering: all have
  defaults already, so appending a defaulted field is safe).
- Do not reorder existing fields.

---

## Acceptance Criteria

- [ ] All three events accept and default `agent_name=None`.
- [ ] Events remain frozen (mutation raises `FrozenInstanceError`).
- [ ] `to_dict()` still passes its strict `json.dumps` validation with `agent_name` set and unset.
- [ ] Existing construction sites compile unchanged (no positional breakage).
- [ ] `ruff check` passes.

---

## Test Specification

```python
def test_after_client_event_agent_name_default_none():
    from parrot.core.events.lifecycle.events.client import AfterClientCallEvent
    # construct with the project's required trace_context fixture
    ev = AfterClientCallEvent(trace_context=..., client_name="openai", model="gpt-4o")
    assert ev.agent_name is None

def test_after_client_event_agent_name_set_and_serializable():
    ev = AfterClientCallEvent(trace_context=..., client_name="openai",
                              model="gpt-4o", agent_name="porygon")
    assert ev.agent_name == "porygon"
    assert "porygon" in str(ev.to_dict())
```

---

## Agent Instructions

Standard SDD flow. Reuse the existing trace_context construction pattern from
the current event tests. Move to `sdd/tasks/completed/` and update the index.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
