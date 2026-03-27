# TASK-467: Route Registration for Understanding Handler

**Feature**: image-video-understanding-handler
**Spec**: `sdd/specs/image-video-understanding-handler.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-466
**Assigned-to**: unassigned

---

## Context

Wire the `UnderstandingHandler` into the application's route registry so it is
discoverable and mountable at startup. Implements **Module 3** from the spec.

---

## Scope

- Import `UnderstandingHandler` in `parrot/handlers/__init__.py`.
- Add it to the `__all__` list (or equivalent export mechanism).
- If the project uses a centralized `setup_routes()` or app-factory pattern, register
  `UnderstandingHandler.setup(app)` there as well.
- Verify the handler is importable from `parrot.handlers`.

**NOT in scope**: handler logic changes, new tests beyond import verification.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/__init__.py` | MODIFY | Import and export `UnderstandingHandler` |

---

## Implementation Notes

### Pattern to Follow
```python
# In parrot/handlers/__init__.py — follow existing import patterns
from .understanding import UnderstandingHandler  # noqa: F401
```

Check how other handlers like `LyriaMusicHandler` or `VideoReelHandler` are
registered and follow the same pattern exactly.

### Key Constraints
- Do not change any existing imports or exports.
- If a `setup_routes()` function exists, add the new handler there.

### References in Codebase
- `parrot/handlers/__init__.py` — existing registration pattern
- `parrot/handlers/lyria_music.py` — reference for how handlers are exported

---

## Acceptance Criteria

- [ ] `from parrot.handlers import UnderstandingHandler` works
- [ ] No import errors introduced for existing handlers
- [ ] Handler is registered in app routes (if centralized setup exists)

---

## Test Specification

```python
# Minimal — verify import works
def test_understanding_handler_importable():
    from parrot.handlers import UnderstandingHandler
    assert UnderstandingHandler is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read** `parrot/handlers/__init__.py` to understand existing pattern
2. **Check dependencies** — verify TASK-466 is in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** the route registration
5. **Verify** the import works
6. **Move this file** to `tasks/completed/TASK-467-understanding-route-registration.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-03-27
**Notes**: Added lazy import for UnderstandingHandler in parrot/handlers/__init__.py following the existing __getattr__ pattern. Import verified.

**Deviations from spec**: none
