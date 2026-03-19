# TASK-196: IPS Exports Update

**Feature**: Investment Policy Statement (FEAT-027)
**Spec**: `sdd/specs/finance-investment-policy-statement.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (30min)
**Depends-on**: TASK-190
**Assigned-to**: claude-session

---

## Context

> Export `InvestmentPolicyStatement` from `parrot/finance/__init__.py` so users
> can import it from the top-level package.

---

## Scope

- Add `InvestmentPolicyStatement` to `parrot/finance/__init__.py` exports

**NOT in scope**: Any implementation changes (done in TASK-190).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/__init__.py` | MODIFY | Export `InvestmentPolicyStatement` |

---

## Acceptance Criteria

- [ ] `from parrot.finance import InvestmentPolicyStatement` works
- [ ] `ruff check parrot/finance/__init__.py` passes
- [ ] All existing imports still resolve

---

## Agent Instructions

1. Read `parrot/finance/__init__.py`
2. Add `InvestmentPolicyStatement` following existing export patterns
3. Verify: `source .venv/bin/activate && python -c "from parrot.finance import InvestmentPolicyStatement; print('OK')"`
4. Run `ruff check parrot/finance/__init__.py`

---

## Completion Note

Added `InvestmentPolicyStatement` to the `from .schemas import (...)` block in
`parrot/finance/__init__.py` and to `__all__`. Import verified (`OK: <class ...>`)
and `ruff check` passes clean.
