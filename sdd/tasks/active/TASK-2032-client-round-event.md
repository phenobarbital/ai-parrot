# TASK-2032: ClientRoundEvent lifecycle event

**Feature**: FEAT-397 — Per-Round Token Usage Observability
**Spec**: `sdd/specs/tokens-observability.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2. The new per-round lifecycle event that carries each tool
round's usage to subscribers (MetricsSubscriber in TASK-2039, plus any
user-registered listener). Must satisfy the strict JSON contract of
`LifecycleEvent.to_dict()`.

---

## Scope

- Add `ClientRoundEvent` frozen dataclass to
  `parrot/core/events/lifecycle/events/client.py` exactly per spec §2
  Data Models:
  - `client_name: str = ""`, `model: str = ""`,
    `round_number: int = 0` (1-indexed),
    `input_tokens/output_tokens/total_tokens: Optional[int] = None`,
    `tool_calls: tuple = ()` (tool-name strings),
    `duration_ms: float = 0.0` (this round's SDK call),
    `raw_usage: Optional[dict] = None` (provider-native, JSON-safe),
    `agent_name: Optional[str] = None` (FEAT-228).
- Export from `parrot/core/events/lifecycle/events/__init__.py`
  (import block + `__all__`).
- Unit test: frozen, defaults, `to_dict()` JSON round-trip (tuple→list),
  `event_class` hint present.

**NOT in scope**: the emit helper (TASK-2033), any client loop change,
any subscriber change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` | MODIFY | Add `ClientRoundEvent` |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/__init__.py` | MODIFY | Export it |
| `packages/ai-parrot/tests/unit/events/lifecycle/test_client_round_event.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from dataclasses import dataclass                       # stdlib
from typing import Optional                             # stdlib
from navigator_eventbus.lifecycle.base import LifecycleEvent
# ^ verified: events/client.py already imports LifecycleEvent this way
from parrot.core.events.lifecycle.events.client import AfterClientCallEvent  # sibling, line 42
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py
@dataclass(frozen=True)
class AfterClientCallEvent(LifecycleEvent):             # line 42 — style model
    client_name: str = ""
    model: str = ""
    duration_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    agent_name: Optional[str] = None

@dataclass(frozen=True)
class PromptCacheAppliedEvent(LifecycleEvent):          # line 124
    segment_hashes: tuple = ()   # ← precedent for tuple fields on frozen events

# navigator_eventbus/lifecycle/base.py (installed package — verified)
class LifecycleEvent:
    def to_dict(self) -> dict[str, Any]:
        # converts tuple→list, then STRICT json.dumps validation.
        # Any non-JSON field value raises TypeError at emit time.

# events/__init__.py: client-event import block starts at line 23;
# __all__ list starts at line 47 (contains "AfterClientCallEvent" at line 59).
```

### Does NOT Exist
- ~~`ClientRoundEvent`~~ — created by THIS task; grep for "round" in the
  events package returns zero results today
- ~~`parrot/core/events/lifecycle/base.py`~~ — moved to
  `navigator_eventbus.lifecycle.base` (TASK-1820); do NOT import the old path
- ~~a `usage: CompletionUsage` field~~ — FORBIDDEN: nested Pydantic models
  fail `to_dict()`'s strict JSON check. Flat ints + dicts only.

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror AfterClientCallEvent's docstring style (Attributes section,
# PII note on agent_name) and PromptCacheAppliedEvent's tuple handling note.
```

### Key Constraints
- Frozen dataclass; every field JSON-serializable (str/int/float/dict/tuple/None).
- Docstring must state: NOT emitted on single-round calls; token fields
  None when the provider reported no usage for the round; `raw_usage` is
  provider-native and must never contain prompt content or PII.
- Keep field order: required-context fields first, matching siblings.

---

## Acceptance Criteria

- [ ] `ClientRoundEvent` exists, frozen, all defaults as specified.
- [ ] Exported: `from parrot.core.events.lifecycle.events import ClientRoundEvent` works.
- [ ] `event.to_dict()` passes (json.dumps-clean; `tool_calls` becomes a list; `event_class == "ClientRoundEvent"`).
- [ ] Tests pass: `pytest packages/ai-parrot/tests/unit/events/lifecycle/test_client_round_event.py -v`
- [ ] Existing event tests pass: `pytest packages/ai-parrot/tests/unit/events/ -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/events/lifecycle/test_client_round_event.py
import json
import dataclasses
import pytest
from parrot.core.events.lifecycle.events import ClientRoundEvent

def test_defaults_and_frozen():
    e = ClientRoundEvent(client_name="anthropic", model="claude-x", round_number=1)
    assert e.input_tokens is None and e.raw_usage is None and e.tool_calls == ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.round_number = 2

def test_to_dict_json_safe():
    e = ClientRoundEvent(
        client_name="openai", model="gpt-x", round_number=2,
        input_tokens=100, output_tokens=20, total_tokens=120,
        tool_calls=("get_weather", "search"), raw_usage={"prompt_tokens": 100},
    )
    d = e.to_dict()
    json.dumps(d)  # must not raise
    assert d["tool_calls"] == ["get_weather", "search"]
    assert d["event_class"] == "ClientRoundEvent"
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/tokens-observability.json` → `"in-progress"`
5. **Implement**, **verify**, move this file to `sdd/tasks/completed/`, update index → `"done"`, fill in the Completion Note

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
