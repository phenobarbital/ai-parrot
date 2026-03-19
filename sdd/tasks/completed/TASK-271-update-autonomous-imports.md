# TASK-271: Update parrot/autonomous/ Imports

**Feature**: Shared Hooks Infrastructure (FEAT-040)
**Spec**: `sdd/specs/integrations-hooks.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-269, TASK-270
**Assigned-to**: claude-session

---

## Context

> Update all imports in `parrot/autonomous/` to reference the new canonical locations
> in `parrot/core/hooks` and `parrot/core/events`.

---

## Scope

### Files to Modify

| File | Action | Description |
|---|---|---|
| `parrot/autonomous/orchestrator.py` | MODIFY | Update hook and EventBus imports |
| `parrot/autonomous/redis_jobs.py` | CHECK/MODIFY | Update if it imports EventBus or hooks |
| `parrot/autonomous/webhooks.py` | CHECK/MODIFY | Update if it imports hooks |
| `parrot/autonomous/__init__.py` | CHECK/MODIFY | Update if it re-exports hooks or EventBus |
| Any other `parrot/autonomous/*.py` | CHECK/MODIFY | Scan for remaining `from .hooks` or `from .evb` imports |

### Key Import Changes

```python
# orchestrator.py — BEFORE:
from .hooks import BaseHook, HookManager, HookEvent
from .evb import EventBus, Event, EventPriority

# orchestrator.py — AFTER:
from parrot.core.hooks import BaseHook, HookManager, HookEvent
from parrot.core.events import EventBus, Event, EventPriority
```

### Implementation Notes

- Search ALL files in `parrot/autonomous/` for imports from `.hooks`, `.evb`, `parrot.autonomous.hooks`, `parrot.autonomous.evb`.
- Update each import to the new `parrot.core.*` path.
- Run existing autonomous tests to verify nothing breaks.

---

## Acceptance Criteria

- [ ] `parrot/autonomous/orchestrator.py` imports from `parrot.core.hooks` and `parrot.core.events`
- [ ] No file in `parrot/autonomous/` imports from `.hooks` or `.evb` with relative imports (except thin re-import files)
- [ ] All existing autonomous tests pass
- [ ] `ruff check parrot/autonomous/` passes

---

## Agent Instructions

1. Grep `parrot/autonomous/` for all hook and evb imports
2. Update each file's imports to `parrot.core.hooks` / `parrot.core.events`
3. Run `ruff check parrot/autonomous/`
4. Run `pytest tests/autonomous/ -v` (if tests exist)
5. Update status → `done`, move to `sdd/tasks/completed/`
