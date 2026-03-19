# TASK-272: HookManager EventBus Dual-Emit

**Feature**: Shared Hooks Infrastructure (FEAT-040)
**Spec**: `sdd/specs/integrations-hooks.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-269, TASK-270
**Assigned-to**: null

---

## Context

> Enhance `HookManager` to optionally emit events to `EventBus` in addition to the direct callback.
> This enables distributed hook consumption and multi-consumer patterns.

---

## Scope

### Files to Modify

| File | Action | Description |
|---|---|---|
| `parrot/core/hooks/manager.py` | MODIFY | Add `set_event_bus()` and dual-emit logic |

### API Addition

```python
class HookManager:
    def set_event_bus(self, bus: EventBus) -> None:
        """Set an optional EventBus for distributed event publishing.

        When set, every hook event is also published to the EventBus
        on channel 'hooks.<hook_type>.<event_type>'.
        """
```

### Implementation Notes

- Import `EventBus` with `TYPE_CHECKING` guard to avoid circular imports.
- In the internal event dispatch (where callback is invoked), add:
  ```python
  if self._event_bus:
      await self._event_bus.emit(
          f"hooks.{event.hook_type.value}.{event.event_type}",
          event.model_dump()
      )
  ```
- Must be backward compatible — if no bus is set, behavior is identical to current.
- The `EventBus` import should be lazy or guarded since not all consumers will use it.

---

## Acceptance Criteria

- [ ] `HookManager.set_event_bus(bus)` method exists
- [ ] When bus is set, hook events are emitted to both callback and bus
- [ ] When bus is NOT set, only callback is invoked (existing behavior)
- [ ] EventBus channel follows pattern `hooks.<hook_type>.<event_type>`
- [ ] `ruff check parrot/core/hooks/manager.py` passes
- [ ] Unit test verifies dual-emit behavior

---

## Agent Instructions

1. Read `parrot/core/hooks/manager.py` (after TASK-269 moves it)
2. Add `set_event_bus()` method
3. Modify event dispatch to dual-emit
4. Write unit test for dual-emit
5. Run `ruff check parrot/core/hooks/manager.py`
6. Update status → `done`, move to `sdd/tasks/completed/`

---

## Completion Note

Completed 2026-03-10.

- Added `_event_bus: Optional[EventBus]` field to `HookManager.__init__`.
- Added `set_event_bus(bus)` method — stores bus, rebuilds and re-injects dispatch callback into all registered hooks.
- Added `_build_dispatch()` — returns raw callback when no bus is set (zero behavior change), or an async `_dual_emit` wrapper when bus is attached. The wrapper calls the user callback first, then `bus.emit("hooks.<hook_type>.<event_type>", event.model_dump())`. EventBus emit failures are caught and logged as warnings so they never surface to callers.
- Updated `register()` to use `_build_dispatch()` so hooks registered after `set_event_bus()` also get dual-emit.
- `EventBus` imported under `TYPE_CHECKING` guard — no circular import, no runtime overhead.
- `ruff check` passes clean.
- 11 unit tests in `tests/core/hooks/test_hookmanager_eventbus.py` — all passing.
