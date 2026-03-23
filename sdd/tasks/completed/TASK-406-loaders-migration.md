# TASK-406: Loaders Package Setup & Migration

**Feature**: monorepo-migration
**Spec**: `sdd/specs/monorepo-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-400
**Assigned-to**: unassigned

---

## Context

Creates the `ai-parrot-loaders` package and moves all loaders from `parrot/loaders/` to `parrot_loaders/`. Fewer loaders than tools, so this is a single task (not batched). `BaseLoader` / abstract base stays in core.

Implements: Spec Module 9 — Loaders Package Setup & Migration.

---

## Scope

- Finalize `packages/ai-parrot-loaders/pyproject.toml`:
  - Per-loader optional extras: `youtube`, `audio`, `pdf`, `web`, `ebook`, `video`, `all`
  - Correct dependency lists per extra
- Move ALL loaders from `packages/ai-parrot/src/parrot/loaders/` to `packages/ai-parrot-loaders/src/parrot_loaders/`:
  - youtube, pdf, audio, markdown, web, video, ppt, epub, etc.
  - Use `git mv` to preserve history
- Keep in core: `abstract.py` (BaseLoader), `__init__.py` (proxy)
- Create `LOADER_REGISTRY` in `parrot_loaders/__init__.py`
- Verify backward-compat imports via proxy
- Update `_get_loader()` in `parrot/handlers/chat.py` if needed (proxy should handle transparently)

**NOT in scope**: Tool migration. Discovery system.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/pyproject.toml` | MODIFY | Per-loader extras with deps |
| `packages/ai-parrot-loaders/src/parrot_loaders/...` | CREATE (via git mv) | All loader directories |
| `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py` | MODIFY | LOADER_REGISTRY |
| `packages/ai-parrot/src/parrot/loaders/` | MODIFY | Only proxy + abstract remain |

---

## Acceptance Criteria

- [ ] All loaders moved to `parrot_loaders/`
- [ ] `LOADER_REGISTRY` populated
- [ ] `from parrot.loaders.youtube import YoutubeLoader` works via proxy
- [ ] `from parrot_loaders.youtube import YoutubeLoader` works directly
- [ ] `from parrot.loaders import BaseLoader` works without `ai-parrot-loaders`
- [ ] `_get_loader()` in handlers still resolves loaders correctly
- [ ] Per-loader extras in pyproject.toml correct
- [ ] All existing tests pass

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
