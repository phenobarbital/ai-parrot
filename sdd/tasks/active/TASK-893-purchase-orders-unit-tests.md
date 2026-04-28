# TASK-893: Unit tests for purchase_orders date sanitization

**Feature**: wm-assembly-purchase-orders-date-sanitization
**Feature ID**: FEAT-130
**Spec**: sdd/specs/wm-assembly-purchase-orders-date-sanitization.spec.md
**Jira**: NAV-8241
**Status**: [ ] pending
**Priority**: medium
**Depends-on**: TASK-891
**Assigned-to**: unassigned

## Context

The date-sanitization logic introduced in TASK-891 must be covered by
automated tests so that regressions are caught before deployment.

## Scope

Create the test file:
`tests/wm_assembly/test_purchase_orders.py`

Tests must cover:

1. `test_hash_overflow_date_becomes_null` — a DataFrame with
   `delivery_date='########'` is processed; output row has
   `delivery_date` as `None` / `pd.NaT` / `NULL`.
2. `test_valid_date_preserved` — a row with `delivery_date='2024-03-15'`
   passes through unchanged.
3. `test_non_parseable_date_becomes_null` — a row with
   `delivery_date='not-a-date'` is coerced to `None`.
4. `test_null_date_preserved` — a row where `delivery_date` is already
   `None` / `NaT` remains `None` (no crash).
5. `test_order_date_sanitized` — same overflow check for `order_date`
   field.

## Files to Create/Modify

- `tests/wm_assembly/__init__.py` — CREATE (empty, if not present)
- `tests/wm_assembly/test_purchase_orders.py` — CREATE

## Implementation Notes

- Tests should exercise the transformation logic in isolation (pure
  pandas operations), not require a live database or flowtask runtime.
- Use `pandas.DataFrame` fixtures with the minimal columns needed.
- Use `pytest.mark.parametrize` for the overflow/valid/null variants.
- If the sanitization is implemented as a helper function in a
  `parrot_tools` or flowtask plugin module, import and test that
  function directly.
- If the sanitization is purely declarative (JSON config), write tests
  that simulate the transformation with equivalent pandas code.

## Acceptance Criteria

- [ ] All 5 test cases exist and pass with `pytest tests/wm_assembly/test_purchase_orders.py -v`.
- [ ] No existing tests are broken (run `pytest` from repo root).
