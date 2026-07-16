---
type: Wiki Overview
title: 'TASK-1280: Structured tier-transition events on EventEmitterMixin'
id: doc:sdd-tasks-completed-task-1280-tier-events-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 module **C7**. Adds the observability layer the spec
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.human.events
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-1280: Structured tier-transition events on EventEmitterMixin

**Feature**: FEAT-194 — HITL Multi-Tier Escalation Policy
**Spec**: `sdd/specs/hitl-escalation-tier.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1277
**Assigned-to**: unassigned

---

## Context

Implements §3 module **C7**. Adds the observability layer the spec
commits to: structured events fired on every tier transition so
subscribers can build audit / analytics / alerting pipelines.

Open question (spec §8): manager inherits from `EventEmitterMixin`
directly OR exposes an `on_event` callback hook. **Decide as part of
this task**; default to the hook approach if mixin inheritance produces
breaking type hierarchy issues.

---

## Scope

- Create `parrot/human/events.py` with Pydantic models:
  - `HitlTierEnteredEvent(interaction_id, policy_id, tier_level, cause, timestamp)`
  - `HitlTierAdvancedEvent(interaction_id, policy_id, from_level, to_level, cause, timestamp)`
  - `HitlTierActionExecutedEvent(interaction_id, policy_id, tier_level, kind, action_metadata, timestamp)`
  - `HitlTierActionFailedEvent(interaction_id, policy_id, tier_level, kind, reason, timestamp)`
  - `HitlChainExhaustedEvent(interaction_id, policy_id, timestamp)`
- Add a `_HitlEventEmitter` helper in the events module that exposes
  `async emit(event_name: str, payload: BaseModel)`. Two backends:
  - **Preferred**: pass-through to `EventEmitterMixin.emit` if the
    manager inherits from it.
  - **Fallback**: an `on_event: Optional[Callable[[str, BaseModel], Awaitable[None]]]`
    constructor kwarg on `HumanInteractionManager`. When set, the
    manager calls it; when not set, events are dropped silently.
- Update `HumanInteractionManager` to:
  - Accept the `on_event` kwarg.
  - Emit `hitl.tier.entered` from `_escalate_to_next_tier` after the
    cursor is updated.
  - Emit `hitl.tier.action_executed` after a successful non-`INTERACT`
    action.
  - Emit `hitl.tier.action_failed` when an action raises or returns
    `error=True` (replaces the TODO marker left by TASK-1277).
  - Emit `hitl.chain.exhausted` from `_finish_with_timeout` when the
    chain is the cause.
- Event emission is best-effort: a subscriber exception MUST NOT
  abort the manager flow (catch + log).

**NOT in scope**: Building a concrete subscriber. Pushing events to
external systems. Persisting events long-term (spec defers external
audit storage to V2).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/human/events.py` | CREATE | Event models + `_HitlEventEmitter` helper |
| `packages/ai-parrot/src/parrot/human/manager.py` | MODIFY | Accept `on_event` kwarg; emit events at decision points |
| `packages/ai-parrot/tests/human/test_tier_events.py` | CREATE | Subscriber observes all event types |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing:
from parrot.tools.abstract import EventEmitterMixin              # tools/abstract.py:78
# Pydantic:
from pydantic import BaseModel, Field
from datetime import datetime, timezone
```

### Existing Signatures to Use

```python
# parrot/tools/abstract.py:78 — base mixin
class AbstractTool(EventEmitterMixin, ABC): ...
# Verify EventEmitterMixin's API surface (likely `emit(event_name, payload, source=...)`
# and `on(event_name, callback)`) by reading parrot/events/ (if it exists)
# or parrot/tools/abstract.py around the mixin declaration BEFORE
# committing to the inheritance path.

# parrot/human/manager.py:60-76 — current __init__
# Add: on_event: Optional[Callable[[str, BaseModel], Awaitable[None]]] = None
```

### Does NOT Exist

- ~~`parrot.events.EventBus`~~ — there is no separate bus; events flow
  through `EventEmitterMixin`.
- ~~`hitl.tier.*` event topics~~ — not registered anywhere today.
- ~~Persistent event store~~ — out of scope for V1.

---

## Implementation Notes

### Pattern to Follow

Inspect `EventEmitterMixin` first:

```bash
grep -n "class EventEmitterMixin" packages/ai-parrot/src/parrot/**/*.py
grep -n "def emit\|def on " packages/ai-parrot/src/parrot/events/*.py
```

If the mixin's `emit` signature is straightforward and the manager can
inherit without breaking existing code (e.g., `HumanInteractionManager`
currently does not inherit from any mixin), prefer inheritance.

If inheritance produces problems (MRO, init signature conflicts),
fall back to the constructor hook:

```python
class HumanInteractionManager:
    def __init__(self, *, on_event=None, **kwargs):
        # ...
        self._on_event = on_event

    async def _emit(self, name: str, payload: BaseModel) -> None:
        if self._on_event is None: return
        try:
            await self._on_event(name, payload)
        except Exception:
            self.logger.exception("hitl event subscriber raised: %s", name)
```

### Key Constraints

- Event payloads MUST be Pydantic models, not dicts — gives subscribers
  type safety.
- `timestamp` defaults to `datetime.now(timezone.utc)` via Pydantic
  default_factory.
- Cause values match the literal set in `advance_chain`:
  `"timeout" | "reject" | "business_hours_off" | "action_failed"`. Plus
  `"initial"` for the first tier entered via `request_human_input`.
- A subscriber raising must not crash the manager (catch + log).
- Event names use dot-namespaced strings: `"hitl.tier.entered"`,
  `"hitl.tier.advanced"`, `"hitl.tier.action_executed"`,
  `"hitl.tier.action_failed"`, `"hitl.chain.exhausted"`.

### References in Codebase

- `parrot/tools/abstract.py:78` — `AbstractTool(EventEmitterMixin, ABC)`.
- Spec §3 C7 + §8 open question about inheritance vs hook.

---

## Acceptance Criteria

- [ ] `parrot.human.events` module exports five Pydantic event models.
- [ ] `HumanInteractionManager(on_event=callback)` accepts a callback;
  when omitted, events are silently dropped.
- [ ] Subscriber observes `hitl.tier.entered` for the starting tier.
- [ ] Subscriber observes `hitl.tier.advanced` on every advance with
  correct `cause`.
- [ ] Subscriber observes `hitl.tier.action_executed` after a
  successful Notify/Ticket action.
- [ ] Subscriber observes `hitl.tier.action_failed` when an action
  raises or returns `error=True`.
- [ ] Subscriber observes `hitl.chain.exhausted` when the chain
  terminates.
- [ ] Subscriber exception does NOT propagate to the manager (caught + logged).
- [ ] Decision documented in the completion note: inheritance vs hook.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/human/test_tier_events.py -v`.

---

## Test Specification

```python
# tests/human/test_tier_events.py
class TestEventEmission:
    async def test_emits_tier_entered_on_initial(self): ...
    async def test_emits_tier_advanced_on_timeout(self): ...
    async def test_emits_tier_advanced_on_reject(self): ...
    async def test_emits_action_executed_after_success(self): ...
    async def test_emits_action_failed_on_exception(self): ...
    async def test_emits_chain_exhausted(self): ...
    async def test_subscriber_exception_does_not_abort_flow(self): ...
    async def test_no_emission_when_on_event_is_none(self): ...
```

---

## Agent Instructions

1. Read spec §3 C7 + §8 open question; investigate `EventEmitterMixin`
   to decide inheritance vs hook.
2. Verify TASK-1277 completed.
3. Implement events module, wire emissions, write tests.
4. Document the chosen approach in the completion note.
5. Move to completed.

---

## Completion Note

Implemented 2026-05-21 by sdd-worker (FEAT-194).

**Architecture decision: hook pattern chosen over EventEmitterMixin inheritance.**
The existing `EventRegistry.emit()` expects a `LifecycleEvent` (frozen dataclass with `TraceContext`, `source_type` etc.) — a different base type than the Pydantic models specified by this task. Adding `EventEmitterMixin` to `HumanInteractionManager` would require non-trivial MRO changes, an `_init_events()` call, and coupling HITL to the lifecycle-events infrastructure unnecessarily. The `on_event: Optional[Callable[[str, BaseModel], Awaitable[None]]]` hook is simpler, test-friendly, and keeps HITL self-contained.

- Created `parrot/human/events.py` with 5 Pydantic event models: `HitlTierEnteredEvent`, `HitlTierAdvancedEvent`, `HitlTierActionExecutedEvent`, `HitlTierActionFailedEvent`, `HitlChainExhaustedEvent`.
- `HumanInteractionManager.__init__` accepts `on_event` kwarg; stored as `self._on_event`.
- `_emit(name, payload)` helper: calls `on_event`; catches subscriber exceptions (catch + log, no re-raise).
- Emission points wired: `hitl.tier.entered` (at tier-entry in `_escalate_to_next_tier`), `hitl.tier.advanced` (in `advance_chain`, `_handle_timeout`, action-failed recursion, business-hours skip), `hitl.tier.action_executed` (on success), `hitl.tier.action_failed` (on error=True and exception), `hitl.chain.exhausted` (on no-more-tiers).
- 13 tests; all pass (8 emission tests + 5 model-shape tests).

*(Agent fills this in when done — MUST state whether inheritance or
hook was chosen and why)*
