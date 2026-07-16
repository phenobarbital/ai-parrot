---
type: Wiki Overview
title: 'TASK-1502: Populate agent_name on client events from the ContextVar'
id: doc:sdd-tasks-active-task-1502-client-populate-agent-name-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §2 Overview step 3, §3 Module 4. The client builds its three lifecycle
relates_to:
- concept: mod:parrot.core.events.lifecycle.events.client
  rel: mentions
- concept: mod:parrot.observability.context
  rel: mentions
---

# TASK-1502: Populate agent_name on client events from the ContextVar

**Feature**: FEAT-228 — Per-Agent Cost & Usage Metrics
**Spec**: `sdd/specs/per-agent-cost-usage-metrics.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1499, TASK-1500
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview step 3, §3 Module 4. The client builds its three lifecycle
events while executing inside the bot's invocation scope (where TASK-1501 has
bound the ContextVar). This task reads `current_agent_name.get()` at event
construction time and stamps it onto the event's new `agent_name` field.

---

## Scope

- In `clients/base.py`, at the three event-construction sites, set
  `agent_name=current_agent_name.get()`:
  - `_send_before` → `BeforeClientCallEvent` (~line 455)
  - `_send_after`  → `AfterClientCallEvent`  (~line 497)
  - `_send_failed` → `ClientCallFailedEvent` (~line 534)
- Read the ContextVar defensively: a failed/missing read must yield `None`, never
  raise into the call path.

**NOT in scope**: defining the var (TASK-1499), the event field (TASK-1500),
wrapping the bot (TASK-1501), labels (TASK-1503/1504).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/clients/base.py` | MODIFY | Stamp `agent_name` on the 3 constructed events |
| `packages/ai-parrot/tests/.../test_client_emits_agent_name.py` | CREATE | With var set → event.agent_name matches; unset → None |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.observability.context import current_agent_name  # TASK-1499
from parrot.core.events.lifecycle.events.client import (      # agent_name field from TASK-1500
    BeforeClientCallEvent, AfterClientCallEvent, ClientCallFailedEvent,
)  # verified imports already present: clients/base.py:67-69
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient(EventEmitterMixin, ABC):   # line 242
    # ctor: self._init_events(forward_to_global=False)   # line 340 (isolated registry)
    def _send_before(self, ...) -> TraceContext:  # ~line 430
        event = BeforeClientCallEvent(...)        # line 455
        self.events.emit_nowait(event)            # line 465 (fire-and-forget)
    async def _send_after(self, ...) -> None:     # ~line 484
        event = AfterClientCallEvent(...)         # line 497
        await self.events.emit(event)             # line 508
    async def _send_failed(self, ...) -> None:    # ~line 523
        event = ClientCallFailedEvent(...)        # line 534
        await self.events.emit(event)             # line 544
```

### Does NOT Exist
- ~~`self.agent_name` / `self._agent` on the client~~ — the client has NO bot
  reference; identity ONLY comes from the ContextVar.
- ~~reading the var inside the subscriber~~ — read it HERE, at construction time,
  in the bot's async context (the subscriber may run later / in another task).

---

## Implementation Notes

### Pattern to Follow
```python
# at each construction site
event = AfterClientCallEvent(
    trace_context=...,
    client_name=...,
    model=...,
    ...,
    agent_name=current_agent_name.get(),   # None when no bot scope is active
)
```

### Key Constraints
- Construct the event (and thus call `.get()`) synchronously in the current
  context — this is already the case at lines 455/497/534, so no restructuring.
- `emit_nowait` for BeforeClientCall (line 465) dispatches fire-and-forget AFTER
  construction, so the value is already captured — correct.
- Never let the var read raise: `current_agent_name.get()` cannot raise for a
  ContextVar with a default, but keep the call inline and simple.

---

## Acceptance Criteria

- [ ] With `current_agent_name` bound to `"porygon"`, an emitted `AfterClientCallEvent` has `agent_name == "porygon"`.
- [ ] With no scope active, `agent_name is None`.
- [ ] Applies to all three events (before/after/failed).
- [ ] No change to client call behavior or signatures; existing client tests pass.
- [ ] `ruff check` passes.

---

## Test Specification

```python
async def test_client_stamps_agent_name():
    from parrot.observability.context import agent_identity
    client = StubClient(...)   # captures emitted events via a test subscriber
    with agent_identity("porygon"):
        await client._send_after(...)   # or drive a full mocked call
    assert captured_after.agent_name == "porygon"

async def test_client_agent_name_none_without_scope():
    await client._send_after(...)
    assert captured_after.agent_name is None
```

---

## Agent Instructions

Standard SDD flow. Verify lines 455/497/534 are still the construction sites
(code may shift) before editing. Move to `completed/`, update the index.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
