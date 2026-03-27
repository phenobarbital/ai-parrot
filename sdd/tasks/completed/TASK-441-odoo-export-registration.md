# TASK-441 — Odoo Interface Export & Registration

**Feature**: FEAT-054 — odoo-interface
**Status**: pending
**Priority**: medium
**Effort**: S
**Depends on**: TASK-375

---

## Objective

Export `OdooInterface` from the `parrot.interfaces` package so it can be imported directly.

## File(s) to Modify

- `parrot/interfaces/__init__.py`

## Implementation Details

1. Add import: `from .odoointerface import OdooInterface`
2. Add `'OdooInterface'` to the `__all__` list.

## Acceptance Criteria

- [ ] `from parrot.interfaces import OdooInterface` works.
- [ ] `from parrot.interfaces.odoointerface import OdooInterface` also works.
- [ ] No circular import issues.

## Tests

- `test_import_odoo_interface` — verify import succeeds.
