# TASK-268: Create parrot/core/ Package

**Feature**: Shared Hooks Infrastructure (FEAT-040)
**Spec**: `sdd/specs/integrations-hooks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: none
**Assigned-to**: null

---

## Context

> Create the `parrot/core/` package as the new shared infrastructure location.
> This is the foundation for all subsequent tasks in FEAT-040.

---

## Scope

### Files to Create

| File | Action | Description |
|---|---|---|
| `parrot/core/__init__.py` | CREATE | Package init — minimal, no eager imports |

### Implementation Notes

- The `__init__.py` should have a module docstring explaining `parrot/core/` is for shared infrastructure reused across `parrot/autonomous`, `parrot/integrations`, and other subsystems.
- Do NOT eagerly import hooks or events — subpackages handle their own imports.
- Verify no circular imports are introduced.

---

## Acceptance Criteria

- [ ] `parrot/core/__init__.py` exists
- [ ] `import parrot.core` works without errors
- [ ] `ruff check parrot/core/` passes

---

## Agent Instructions

1. Create `parrot/core/__init__.py` with a docstring
2. Verify `import parrot.core` works
3. Run `ruff check parrot/core/`
4. Update status → `done`, move to `sdd/tasks/completed/`
