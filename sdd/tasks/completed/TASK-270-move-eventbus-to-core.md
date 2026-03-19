# TASK-270: Move EventBus to parrot/core/events/

**Feature**: Shared Hooks Infrastructure (FEAT-040)
**Spec**: `sdd/specs/integrations-hooks.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-268
**Assigned-to**: claude-session

---

## Context

> Move `EventBus` from `parrot/autonomous/evb.py` to `parrot/core/events/evb.py`.
> The EventBus provides Redis-backed pub/sub with glob-pattern matching and event history.

---

## Scope

### Files to Create / Move

| File | Action | Description |
|---|---|---|
| `parrot/core/events/__init__.py` | CREATE | Exports: `EventBus`, `Event`, `EventPriority`, `EventSubscription` |
| `parrot/core/events/evb.py` | MOVE | From `parrot/autonomous/evb.py` |

### Files to Modify

| File | Action | Description |
|---|---|---|
| `parrot/autonomous/evb.py` | REPLACE | Thin re-import: `from parrot.core.events.evb import *` |

### Implementation Notes

- Use `git mv` for `evb.py` to preserve history.
- Create `parrot/core/events/__init__.py` that re-exports the key classes.
- Check `evb.py` for any absolute imports referencing `parrot.autonomous` and update.
- Replace `parrot/autonomous/evb.py` with thin re-import as transitional step.

---

## Acceptance Criteria

- [x] `parrot/core/events/evb.py` exists with full EventBus implementation
- [x] `from parrot.core.events import EventBus, Event, EventPriority` works
- [x] `ruff check parrot/core/events/` passes
- [x] No circular imports

---

## Agent Instructions

1. Create `parrot/core/events/` directory
2. `git mv parrot/autonomous/evb.py parrot/core/events/evb.py`
3. Create `parrot/core/events/__init__.py` with exports
4. Scan `evb.py` for absolute imports referencing `parrot.autonomous` and update
5. Create thin `parrot/autonomous/evb.py` re-import
6. Verify imports work
7. Run `ruff check parrot/core/events/`
8. Update status → `done`, move to `sdd/tasks/completed/`
