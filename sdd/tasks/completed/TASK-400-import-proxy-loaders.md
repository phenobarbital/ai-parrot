# TASK-400: Import Proxy — Loaders

**Feature**: monorepo-migration
**Spec**: `sdd/specs/monorepo-migration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-398
**Assigned-to**: unassigned

---

## Context

Same pattern as TASK-399 but for loaders. Creates the `__getattr__`-based proxy in `parrot/loaders/__init__.py` that resolves imports from `parrot_loaders` package. `BaseLoader` and abstract base stay in core.

Implements: Spec Module 3 — Import Proxy (Loaders).

---

## Scope

- Replace `parrot/loaders/__init__.py` with `__getattr__` proxy that:
  1. Tries `parrot_loaders.<name>` (installed ai-parrot-loaders package)
  2. Tries `plugins.loaders.<name>` (user plugins)
  3. Falls back to `LOADER_REGISTRY` in `parrot_loaders`
  4. Raises clear `ImportError` with install instructions
- Keep direct re-exports of `BaseLoader` / `AbstractLoader` (stays in core)

**NOT in scope**: Moving loader code. Tools proxy (TASK-399).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/loaders/__init__.py` | MODIFY | Replace with __getattr__ proxy + base class re-exports |

---

## Acceptance Criteria

- [ ] `from parrot.loaders import BaseLoader` works without `ai-parrot-loaders`
- [ ] When `ai-parrot-loaders` IS installed: `from parrot.loaders.youtube import YoutubeLoader` works
- [ ] When `ai-parrot-loaders` NOT installed: clear `ImportError` with install instructions
- [ ] All existing tests pass

---

## Agent Instructions

When you pick up this task:

1. **Read current `parrot/loaders/__init__.py`** to understand existing exports
2. **Follow same pattern as TASK-399** (tools proxy)
3. **Update status** → `"in-progress"`, implement, verify, complete

---

## Completion Note

**Completed by**: Claude Opus 4.6
**Date**: 2026-03-23
**Notes**: Implemented `__getattr__` proxy following same pattern as TASK-399 (tools proxy). Resolution chain: `parrot_loaders` → `plugins.loaders` → `LOADER_REGISTRY` → `dynamic_import_helper`. Core re-exports: `AbstractLoader`, `Document`.

**Deviations from spec**: none
