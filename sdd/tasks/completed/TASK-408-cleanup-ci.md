# TASK-408: Cleanup & CI

**Feature**: monorepo-migration
**Spec**: `sdd/specs/monorepo-migration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-403, TASK-404, TASK-405, TASK-406, TASK-407
**Assigned-to**: unassigned

---

## Context

Post-migration cleanup: remove empty directories from core, update CI pipeline, ensure version synchronization, update `.gitignore`, verify workspace-level operations.

Implements: Spec Module 11 — Cleanup & CI.

---

## Scope

- Remove empty tool/loader directories from `packages/ai-parrot/src/parrot/tools/` (only proxy, base classes, core tools, and discovery should remain)
- Remove empty loader directories from `packages/ai-parrot/src/parrot/loaders/` (only proxy + abstract)
- Update CI (GitHub Actions or equivalent) to:
  - Run `uv sync --all-packages`
  - Run `python scripts/generate_tool_registry.py --check`
  - Run tests with all packages
- Update `.gitignore` if needed for workspace artifacts
- Verify version numbers synchronized across all 3 `pyproject.toml` files
- Update root README if it references old import paths

**NOT in scope**: Writing new tests (TASK-409).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/` | CLEANUP | Remove empty dirs |
| `packages/ai-parrot/src/parrot/loaders/` | CLEANUP | Remove empty dirs |
| `.github/workflows/` or CI config | MODIFY | Add workspace sync + registry check |
| `.gitignore` | MODIFY | Add workspace-specific entries if needed |

---

## Acceptance Criteria

- [ ] No empty tool/loader directories in core
- [ ] CI runs `uv sync --all-packages` and tests
- [ ] CI runs `generate_tool_registry.py --check`
- [ ] All 3 packages have same version number
- [ ] `uv sync --all-packages` from clean clone works

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
