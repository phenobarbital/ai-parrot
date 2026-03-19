# TASK-007: Register VideoReelHandler Routes

**Feature**: REST API — Generate Video Reel
**Spec**: `docs/sdd/specs/rest-api-generate-video-reel.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-005
**Assigned-to**: 6dbd6c81-1df6-47ce-8a07-afe0cf2c4e7f

---

## Context

> Implements Section 3 — Module 3 of the spec.
> Makes `VideoReelHandler` discoverable by adding a lazy import in `parrot/handlers/__init__.py`, following the existing pattern for `LyriaMusicHandler`.

---

## Scope

- Add `VideoReelHandler` lazy import in `parrot/handlers/__init__.py` via the existing `__getattr__` mechanism.

**NOT in scope**: handler implementation (TASK-005), tests (TASK-008).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/__init__.py` | MODIFY | Add `VideoReelHandler` to lazy `__getattr__` |

---

## Implementation Notes

### Pattern to Follow
```python
# parrot/handlers/__init__.py — existing __getattr__:
def __getattr__(name: str):
    if name == "LyriaMusicHandler":
        from .lyria_music import LyriaMusicHandler
        return LyriaMusicHandler
    # ADD:
    if name == "VideoReelHandler":
        from .video_reel import VideoReelHandler
        return VideoReelHandler
    raise AttributeError(...)
```

### Key Constraints
- Follow the existing lazy import pattern exactly
- Add the new block before the `raise AttributeError` line

### References in Codebase
- `parrot/handlers/__init__.py` — current lazy imports
- `parrot/handlers/lyria_music.py` — reference pattern

---

## Acceptance Criteria

- [ ] `from parrot.handlers import VideoReelHandler` works without error
- [ ] Existing imports (`ChatbotHandler`, `LyriaMusicHandler`, etc.) unaffected
- [ ] No linting errors: `ruff check parrot/handlers/__init__.py`

---

## Test Specification

| Test | Description |
|---|---|
| `test_import_video_reel_handler` | `from parrot.handlers import VideoReelHandler` succeeds |

*(Verified as part of TASK-008 or manually)*

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-005 must be in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-007-register-video-reel-handler.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 6dbd6c81-1df6-47ce-8a07-afe0cf2c4e7f
**Date**: 2026-02-19
**Notes**: Added `VideoReelHandler` lazy import to `parrot/handlers/__init__.py` `__getattr__` function.

**Deviations from spec**: none
