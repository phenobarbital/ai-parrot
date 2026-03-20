# TASK-182: Exports Update

**Feature**: Multi-Executor Integration (FEAT-026)
**Spec**: `sdd/specs/finance-multi-executor-integration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-177, TASK-179
**Assigned-to**: unassigned

---

## Context

> Update package `__init__.py` files to export new public symbols:
> `create_ibkr_executor`, `create_ibkr_executor_profile`, `RoutingMode`.

---

## Scope

- Export `create_ibkr_executor` from `parrot/finance/agents/__init__.py`
- Export `create_ibkr_executor_profile` and `RoutingMode` from `parrot/finance/__init__.py`

**NOT in scope**: Implementation of functions (done in TASK-177 and TASK-179).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/agents/__init__.py` | MODIFY | Export create_ibkr_executor |
| `parrot/finance/__init__.py` | MODIFY | Export create_ibkr_executor_profile, RoutingMode |

---

## Implementation Notes

- Follow existing export patterns in both files
- Check existing `__all__` lists or import patterns

---

## Acceptance Criteria

- [ ] `from parrot.finance.agents import create_ibkr_executor` works
- [ ] `from parrot.finance import create_ibkr_executor_profile, RoutingMode` works
- [ ] Ruff check passes on both files
- [ ] All existing imports still resolve

---

## Agent Instructions

1. Open both `__init__.py` files
2. Add exports following existing patterns
3. Run `ruff check parrot/finance/agents/__init__.py parrot/finance/__init__.py`
4. Run import checks
