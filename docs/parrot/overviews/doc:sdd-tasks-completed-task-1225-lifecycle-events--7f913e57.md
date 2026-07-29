---
type: Wiki Overview
title: 'TASK-1225: PromptCacheAppliedEvent + PromptCacheSkippedEvent lifecycle events'
id: doc:sdd-tasks-completed-task-1225-lifecycle-events-prompt-cache-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task adds two new lifecycle event dataclasses (spec Module 9, §3) for
relates_to:
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.events.client
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
---

# TASK-1225: PromptCacheAppliedEvent + PromptCacheSkippedEvent lifecycle events

**Feature**: FEAT-181 — Provider-Agnostic Prompt Caching
**Spec**: `sdd/specs/agnostic-prompt-caching-abstraction.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task adds two new lifecycle event dataclasses (spec Module 9, §3) for
observing prompt caching behavior. These events allow monitoring tools to track
cache hits, misses, and skip reasons across providers. They follow the existing
FEAT-176 lifecycle events pattern — frozen dataclasses inheriting from
`LifecycleEvent`.

---

## Scope

- Add `PromptCacheAppliedEvent` and `PromptCacheSkippedEvent` as frozen
  dataclasses in `parrot/core/events/lifecycle/events/client.py`.
- Follow the `_system_prompt_hash` privacy pattern — segment hashes use SHA-256,
  never raw content.
- Export from the events `__init__.py`.
- Write unit tests.

**NOT in scope**: Emitting these events from client translators (that happens
in TASK-1222–1224 and TASK-1220). This task only creates the event classes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/client.py` | MODIFY | Add two new event dataclasses |
| `packages/ai-parrot/src/parrot/core/events/lifecycle/events/__init__.py` | MODIFY | Export new events |
| `packages/ai-parrot/tests/test_prompt_cache_events.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.core.events.lifecycle.base import LifecycleEvent  # base.py:21
from parrot.core.events.lifecycle.trace import TraceContext     # used by all events
from parrot.core.events.lifecycle.events.client import (
    BeforeClientCallEvent,   # client.py:18
    AfterClientCallEvent,    # client.py:38
    ClientCallFailedEvent,   # client.py:62
    ClientStreamChunkEvent,  # client.py:83
)
```

### Existing Signatures to Use
```python
# parrot/core/events/lifecycle/base.py
@dataclass(frozen=True)
class LifecycleEvent(ABC):               # line 21
    trace_context: TraceContext           # required, no default
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_type: str = ""                # "agent" | "client" | "tool"
    source_name: str = ""

# parrot/core/events/lifecycle/events/client.py — pattern:
@dataclass(frozen=True)
class BeforeClientCallEvent(LifecycleEvent):  # line 18
    client_name: str = ""
    model: str = ""
    temperature: Optional[float] = None
    system_prompt_hash: str = ""
    has_tools: bool = False

# parrot/core/events/lifecycle/events/__init__.py — exports:
# Check current exports and add the new events
```

### Does NOT Exist
- ~~`PromptCacheAppliedEvent`~~ — does not exist; this task creates it
- ~~`PromptCacheSkippedEvent`~~ — does not exist; this task creates it
- ~~`parrot.core.events.lifecycle.events.cache`~~ — no such module; events go in `client.py`

---

## Implementation Notes

### Pattern to Follow

Follow the exact pattern of `BeforeClientCallEvent` — frozen dataclass,
inherits `LifecycleEvent`, all fields have defaults:

```python
@dataclass(frozen=True)
class PromptCacheAppliedEvent(LifecycleEvent):
    """Emitted when prompt caching is applied to an LLM call."""
    client_name: str = ""
    model: str = ""
    blocks_marked: int = 0          # number of cache_control blocks applied
    est_tokens: int = 0             # estimated cacheable token count
    segment_hashes: tuple[str, ...] = ()  # SHA-256 of each cacheable segment

@dataclass(frozen=True)
class PromptCacheSkippedEvent(LifecycleEvent):
    """Emitted when prompt caching is skipped."""
    client_name: str = ""
    model: str = ""
    reason: str = ""  # "below_threshold" | "provider_unsupported" | "feature_off" | "no_segments"
```

### Key Constraints
- All fields must be JSON-serializable (str, int, float, bool, None, list, dict, tuple).
- `segment_hashes` uses `tuple[str, ...]` (not list) for immutability.
- Use SHA-256 for segment hashes — never include raw segment text.
- Frozen dataclass — `@dataclass(frozen=True)`.
- Must be alongside existing client events in `client.py`.

### References in Codebase
- `parrot/core/events/lifecycle/events/client.py` — target file
- `parrot/core/events/lifecycle/base.py` — base class
- `parrot/clients/base.py:340` — `_system_prompt_hash` SHA-256 pattern

---

## Acceptance Criteria

- [ ] `PromptCacheAppliedEvent` is a frozen dataclass inheriting `LifecycleEvent`
- [ ] `PromptCacheSkippedEvent` is a frozen dataclass inheriting `LifecycleEvent`
- [ ] Both have `client_name`, `model` fields matching the existing pattern
- [ ] `PromptCacheAppliedEvent.segment_hashes` is a tuple of SHA-256 strings
- [ ] `PromptCacheSkippedEvent.reason` accepts the 4 defined reason strings
- [ ] Both serialize correctly via `to_dict()`
- [ ] Both are exported from `parrot.core.events.lifecycle.events`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_prompt_cache_events.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/test_prompt_cache_events.py
import pytest
from parrot.core.events.lifecycle.trace import TraceContext
from parrot.core.events.lifecycle.events.client import (
    PromptCacheAppliedEvent,
    PromptCacheSkippedEvent,
)


class TestPromptCacheAppliedEvent:
    def test_creation(self):
        tc = TraceContext.new_root()
        evt = PromptCacheAppliedEvent(
            trace_context=tc,
            client_name="anthropic",
            model="claude-sonnet-4-20250514",
            blocks_marked=2,
            est_tokens=3000,
            segment_hashes=("abc123", "def456"),
            source_type="client",
            source_name="anthropic",
        )
        assert evt.blocks_marked == 2
        assert evt.est_tokens == 3000
        assert len(evt.segment_hashes) == 2

    def test_serialization(self):
        tc = TraceContext.new_root()
        evt = PromptCacheAppliedEvent(
            trace_context=tc,
            client_name="anthropic",
            model="claude-sonnet-4-20250514",
            source_type="client",
            source_name="anthropic",
        )
        d = evt.to_dict()
        assert "client_name" in d
        assert d["event_class"] == "PromptCacheAppliedEvent"

    def test_frozen(self):
        tc = TraceContext.new_root()
        evt = PromptCacheAppliedEvent(trace_context=tc)
        with pytest.raises(AttributeError):
            evt.blocks_marked = 5


class TestPromptCacheSkippedEvent:
    def test_creation_with_reasons(self):
        tc = TraceContext.new_root()
        for reason in ("below_threshold", "provider_unsupported", "feature_off", "no_segments"):
            evt = PromptCacheSkippedEvent(
                trace_context=tc,
                client_name="groq",
                model="llama-3",
                reason=reason,
                source_type="client",
                source_name="groq",
            )
            assert evt.reason == reason

    def test_serialization(self):
        tc = TraceContext.new_root()
        evt = PromptCacheSkippedEvent(
            trace_context=tc,
            reason="below_threshold",
        )
        d = evt.to_dict()
        assert d["reason"] == "below_threshold"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm `client.py` still has the 4
   existing event classes at the listed lines
4. **Read `__init__.py`** to see current exports and add the new ones
5. **Update status** in `sdd/tasks/index/agnostic-prompt-caching-abstraction.json` → `"in-progress"`
6. **Implement** following the scope and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-1225-lifecycle-events-prompt-cache.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any

---

**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-05-18
**Notes**: Added PromptCacheAppliedEvent (blocks_marked, est_tokens, segment_hashes tuple) and PromptCacheSkippedEvent (reason) to client.py. Both exported from __init__.py. All 13 tests pass.
**Deviations from spec**: none
