---
type: Wiki Overview
title: 'TASK-1521: Migrate the 3 payroll toolkit methods to the composable'
id: doc:sdd-tasks-completed-task-1521-migrate-payroll-methods-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2**. The 3 payroll methods are the only ones still on
  the
relates_to:
- concept: mod:parrot_tools.interfaces.workday.service
  rel: mentions
- concept: mod:parrot_tools.workday.tool
  rel: mentions
---

# TASK-1521: Migrate the 3 payroll toolkit methods to the composable

**Feature**: FEAT-233 — Workday Composable-Only WSDL Routing
**Spec**: `sdd/specs/workday-composable-only-wsdl-routing.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1520
**Assigned-to**: unassigned

---

## Context

Implements **Module 2**. The 3 payroll methods are the only ones still on the
legacy SOAP path (`_get_client_for_method` → `wsdl_paths` → `WorkdaySOAPClient`).
Now that the composable has payroll handlers (TASK-1520), migrate these 3 to
delegate via `_get_composable(...)` like the other 22 methods, so the legacy block
can be deleted (TASK-1522).

---

## Scope

- Rewrite the bodies of `wd_get_payroll_balances` (tool.py:1342),
  `wd_get_payroll_results` (tool.py:1390), `wd_get_company_payment_dates`
  (tool.py:1444): replace `client = await self._get_client_for_method(...)` +
  in-line SOAP with `svc = await self._get_composable("get_payroll_...")` →
  `fetch_models`/`fetch` → JSON-serializable `dict`/`list[dict]`.
- Preserve public signatures AND the input schemas `GetPayrollBalancesInput`
  (tool.py:303), `GetPayrollResultsInput` (tool.py:323), `GetCompanyPaymentDatesInput`
  (tool.py:343) — no breaking change.
- No `pandas.DataFrame` may cross the tool boundary (`json.dumps(result)` succeeds).

**NOT in scope:** deleting the legacy block (TASK-1522); changing the 22 other
methods; touching the composable handlers (TASK-1520).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` | MODIFY | rewrite 3 payroll method bodies to delegate to the composable |
| `packages/ai-parrot-tools/tests/workday/test_payroll_methods_delegate.py` | CREATE | delegation + JSON-serializable + signature tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from ..interfaces.workday.service import WorkdayService as WorkdayComposable  # tool.py:75
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/workday/tool.py
async def _get_composable(self, operation_type: str) -> WorkdayComposable: ...  # line 656 (the path to use)
class GetPayrollBalancesInput(BaseModel): ...          # line 303  (KEEP)
class GetPayrollResultsInput(BaseModel): ...           # line 323  (KEEP)
class GetCompanyPaymentDatesInput(BaseModel): ...      # line 343  (KEEP)
async def wd_get_payroll_balances(self, worker_id: str,
                                  start_date: Optional[str] = None, ...): ...   # line 1342 (MIGRATE)
async def wd_get_payroll_results(self, worker_id: str,
                                 start_date: Optional[str] = None, ...): ...     # line 1390 (MIGRATE)
async def wd_get_company_payment_dates(self, start_date: str,
                                       end_date: str, ...): ...                  # line 1444 (MIGRATE)
def _flatten_entries(self, ...): ...                   # ~line 1706 (DataFrame->dict helper, reuse)

# composable (from TASK-1520): operation_types get_payroll_balances /
#   get_payroll_results / get_company_payment_dates are registered + WSDL-routed.
async def fetch(self, operation_type, **params) -> pd.DataFrame   # service.py:266
async def fetch_models(self, operation_type, **params) -> list    # service.py:291
```

### Does NOT Exist
- ~~`_get_client_for_method` is the right path going forward~~ — it is the LEGACY path being retired; use `_get_composable`.
- ~~payroll handlers absent~~ — they exist after TASK-1520; if missing, TASK-1520 is incomplete (check deps first).

---

## Implementation Notes

### Pattern to Follow
```python
@tool_schema(GetPayrollBalancesInput)
async def wd_get_payroll_balances(self, worker_id: str, start_date=None, ...):
    """<unchanged docstring>"""
    svc = await self._get_composable("get_payroll_balances")
    models = await svc.fetch_models("get_payroll_balances",
                                    worker_id=worker_id, start_date=start_date, ...)
    return [m.model_dump(mode="json") for m in models]
    # fallback if untyped: df = await svc.fetch(...); return self._flatten_entries(df.to_dict(orient="records"))
```

### Key Constraints
- Keep signatures + input schemas exactly (backward compat).
- Return JSON-serializable; never a DataFrame.
- Mirror how the other 22 migrated methods call `_get_composable`.

### References in Codebase
- Any already-migrated method (e.g. `get_time_off_balance`) as the delegation template.

---

## Acceptance Criteria

- [ ] The 3 payroll methods delegate via `_get_composable` (no `_get_client_for_method`).
- [ ] Public signatures + input schemas unchanged.
- [ ] Returns are JSON-serializable dict/list[dict] (`json.dumps` ok); no DataFrame.
- [ ] Tests pass: `pytest packages/ai-parrot-tools/tests/workday/test_payroll_methods_delegate.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-tools/src/parrot_tools/workday/tool.py`

---

## Test Specification
```python
# packages/ai-parrot-tools/tests/workday/test_payroll_methods_delegate.py
import json, pytest
from parrot_tools.workday.tool import WorkdayToolkit


@pytest.mark.asyncio
async def test_payroll_methods_delegate_to_composable(monkeypatch):
    calls = {}
    async def fake_fetch_models(self, operation_type, **params):
        calls.setdefault("ops", []).append(operation_type); return []
    monkeypatch.setattr(
        "parrot_tools.interfaces.workday.service.WorkdayService.fetch_models",
        fake_fetch_models)
    # call each wd_get_payroll_* (mock start) and assert composable op used + json.dumps ok
    ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 2, §6). 2. **Check deps** — TASK-1520 completed.
3. **Verify the Codebase Contract**. 4. **Update status** → in-progress.
5. **Implement**. 6. **Verify** criteria. 7. **Move** to completed; **update index** → done.
8. **Fill Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <id>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
