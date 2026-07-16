# TASK-1790: HookManager route_to_bus — hooks publish to the bus by default

**Feature**: FEAT-310 — Unified EventBus v2 — queue-based dispatch, severity, ingress channels, and notifications
**Spec**: `sdd/specs/eventbus-v2.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1786
**Assigned-to**: unassigned

---

## Context

Module 8 of FEAT-310 (spec §3, Phase 3) — goal G5's first half. Today hook
events flow to the orchestrator callback, with the bus only as an optional
secondary dual-emit (`set_event_bus`). This task adds a `route_to_bus` mode
so hooks publish `hooks.<type>.<event>` envelopes as a first-class path.
The orchestrator direct callback is KEPT permanently (*resolved in
brainstorm*) — this is additive, not a replacement.

---

## Scope

- Extend `packages/ai-parrot/src/parrot/core/hooks/manager.py`:
  - New `route_to_bus: bool` mode (constructor kwarg and/or setter): when
    enabled and a bus is set, every hook event publishes topic
    `hooks.<hook_type>.<event_type>` through the EventBus facade with
    severity mapped from event context (default INFO).
  - `set_event_bus()` semantics widened but signature UNCHANGED; existing
    dual-emit behavior preserved when `route_to_bus` is off (default OFF for
    backward compat).
  - Orchestrator callback path untouched.
- Optional flag on `AutonomousOrchestrator` (ai-parrot-server): allow
  `_handle_hook_event` to be re-registered as a bus subscriber behind a
  config flag (default off) — spec §2 integration table. Keep minimal.
- Tests: `test_hookmanager_route_to_bus` — hooks publish envelopes; legacy
  `set_event_bus` dual-emit still works; existing
  `test_hookmanager_eventbus.py` passes UNMODIFIED.

**NOT in scope**: WS/gRPC ingress (TASK-1791), envelope changes, BusCore.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/core/hooks/manager.py` | MODIFY | `route_to_bus` mode |
| `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py` | MODIFY | optional subscribe-flag (small, guarded) |
| `packages/ai-parrot/tests/core/hooks/test_hookmanager_route_to_bus.py` | CREATE | new-mode tests |

> **Guard rail — must pass UNMODIFIED:**
> `packages/ai-parrot/tests/core/hooks/test_hookmanager_eventbus.py`

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` 2026-07-16 (commit b7226186d).

### Verified Imports
```python
from parrot.core.hooks.manager import HookManager          # manager.py:15
from parrot.core.hooks.models import HookEvent, HookType   # models.py:31, models.py:9
from parrot.core.events import EventBus                    # facade (TASK-1786)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/core/hooks/manager.py:15
class HookManager:
    def set_event_bus(self, bus: "EventBus") -> None    # line 43 — dual-emit "hooks.<type>.<event>" exists HERE
    def register(self, hook: BaseHook) -> str           # line 111
    async def start_all(self) -> None                   # line 139
    async def stop_all(self) -> None                    # line 159

# packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py:231
#     self.event_bus = EventBus(...)   ← sole production instantiation
# orchestrator callback: HookManager.set_event_callback → _handle_hook_event (KEEP AS-IS)

# packages/ai-parrot/src/parrot/core/hooks/models.py:31
class HookEvent(BaseModel):
    hook_id: str; hook_type: HookType; event_type: str
    payload: Dict[str, Any]; metadata: Dict[str, Any]
    timestamp: datetime        # naive — converter (TASK-1783 from_hook_event) coerces
```

### Does NOT Exist
- ~~`HookManager.route_to_bus`~~ — created by THIS task; today only optional dual-emit via `set_event_bus`.
- ~~Deprecation of `set_event_callback` / orchestrator callback~~ — explicitly kept (*resolved in brainstorm*); do NOT remove or warn on it.
- ~~`EventBus.publish_envelope()` public method~~ — publish through `emit(topic, payload, **kwargs)` on the facade.

---

## Implementation Notes

### Pattern to Follow
Reuse the existing dual-emit code path in `set_event_bus`/manager dispatch as
the template for topic naming (`hooks.<type>.<event>`); `route_to_bus` should
share one internal `_publish_hook_event()` helper rather than duplicating
string formatting (the spec's whole point is killing duplicated dispatch).

### Key Constraints
- Default OFF: zero behavior change unless explicitly enabled (goal G6).
- Fire-and-forget: publishing must not block hook processing; use the
  facade's `emit` (post-TASK-1786 it is O(1) enqueue).
- Use `from_hook_event` converter semantics via facade kwargs (severity=INFO
  default; correlation/metadata carried from `HookEvent`).
- Orchestrator flag: read via navconfig; guarded so ai-parrot-server tests
  without the flag see identical behavior.

### References in Codebase
- `packages/ai-parrot/tests/core/hooks/test_hookmanager_eventbus.py` — existing contract
- `packages/ai-parrot/src/parrot/core/hooks/manager.py:43` — existing dual-emit

---

## Acceptance Criteria

- [ ] `route_to_bus=True` → hook event published as `hooks.<type>.<event>` envelope (asserted via facade subscription).
- [ ] `route_to_bus` default False → behavior byte-identical to today; `test_hookmanager_eventbus.py` passes UNMODIFIED.
- [ ] Orchestrator callback still invoked in both modes.
- [ ] Optional orchestrator bus-subscription flag defaults off; when on, `_handle_hook_event` receives bus-delivered events.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/core/hooks/ -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/core/hooks/manager.py` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/core/hooks/test_hookmanager_route_to_bus.py
import pytest


async def test_route_to_bus_publishes_envelope(): ...
async def test_route_to_bus_default_off_legacy_dual_emit(): ...
async def test_orchestrator_callback_still_fires(): ...
```

---

## Agent Instructions

1. Read spec §2 (Ingress) and the resolved brainstorm decision: callback is permanent.
2. Verify TASK-1786 is in `sdd/tasks/completed/`.
3. Run the guard-rail test BEFORE and AFTER your change.
4. Update `sdd/tasks/index/eventbus-v2.json` status transitions.
5. Move this file to `sdd/tasks/completed/` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
