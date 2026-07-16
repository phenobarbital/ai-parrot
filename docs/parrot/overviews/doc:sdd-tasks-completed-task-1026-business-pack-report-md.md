---
type: Wiki Overview
title: 'TASK-1026: Business Pack Report (Phase 2)'
id: doc:sdd-tasks-completed-task-1026-business-pack-report-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agents need a quick way to check which modules, models, and capabilities
  are available
---

# TASK-1026: Business Pack Report (Phase 2)

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1013, TASK-1018
**Assigned-to**: unassigned

---

## Context

Agents need a quick way to check which modules, models, and capabilities are available
for a given business domain. This task defines pack expectations and optionally
cross-references against a live Odoo instance.

Implements spec §3 Module 14: Business Pack Report.

---

## Scope

- Add `business_pack_report` async method to `OdooToolkit`
- Define `BUSINESS_PACKS` constant with expected modules and models for:
  `sales`, `crm`, `inventory`, `accounting`, `hr`
- When connected to Odoo, use `get_odoo_profile()` to get installed modules and
  report `installed` vs `missing` split
- When offline, return expected modules/models without live check
- Validate `pack` parameter against known packs; raise `ValueError` for unknown
- Decorate with `@tool_schema(BusinessPackReportInput)`
- Return `BusinessPackResult` envelope

**NOT in scope**: `fit_gap_report`, `scan_addons_source`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY | Add `business_pack_report`, `BUSINESS_PACKS` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .models.inputs import BusinessPackReportInput  # TASK-1013
from .models.envelopes import BusinessPackResult    # TASK-1013
```

### Existing Signatures to Use
```python
# TASK-1018 adds:
async def get_odoo_profile(self, include_modules=True, module_limit=100) -> OdooProfileResult:
```

### Does NOT Exist
- ~~`OdooToolkit.business_pack_report()`~~ — must be created
- ~~`BUSINESS_PACKS`~~ constant — must be created

---

## Implementation Notes

### Pack Definitions (from spec §7)
```python
BUSINESS_PACKS: dict[str, dict[str, Any]] = {
    "sales": {
        "modules": ["sale", "sale_management"],
        "models": ["sale.order", "sale.order.line"],
    },
    "crm": {
        "modules": ["crm"],
        "models": ["crm.lead", "crm.team"],
    },
    "inventory": {
        "modules": ["stock", "stock_account"],
        "models": ["stock.picking", "stock.move"],
    },
    "accounting": {
        "modules": ["account", "account_payment"],
        "models": ["account.move", "account.payment"],
    },
    "hr": {
        "modules": ["hr", "hr_holidays"],
        "models": ["hr.employee", "hr.leave"],
    },
}
```

### Live Check Logic
```python
try:
    profile = await self.get_odoo_profile(include_modules=True)
    installed_names = {m["name"] for m in profile.installed_modules}
    installed = [m for m in expected_modules if m in installed_names]
    missing = [m for m in expected_modules if m not in installed_names]
except OdooError:
    installed, missing = [], []
```

### Key Constraints
- Raise `ValueError` for unknown pack names
- Live check is best-effort — if not connected, return empty installed/missing
- `pack` parameter is case-insensitive (normalise to lowercase)

---

## Acceptance Criteria

- [ ] `business_pack_report(pack="sales")` returns expected modules and models
- [ ] `business_pack_report(pack="hr")` returns HR-specific expectations
- [ ] With live Odoo, reports installed vs missing modules
- [ ] Unknown pack name → `ValueError`
- [ ] Returns `BusinessPackResult` envelope

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_business_pack_sales(odoo_toolkit):
    result = await tk.business_pack_report(pack="sales")
    assert isinstance(result, BusinessPackResult)
    assert "sale" in [m["name"] if isinstance(m, dict) else m for m in result.expected_modules]

@pytest.mark.asyncio
async def test_business_pack_invalid(odoo_toolkit):
    with pytest.raises(ValueError, match="Unknown pack"):
        await tk.business_pack_report(pack="blockchain")

@pytest.mark.asyncio
async def test_business_pack_live_check(odoo_toolkit):
    # Mock get_odoo_profile to return installed modules
    result = await tk.business_pack_report(pack="hr")
    assert isinstance(result.installed, list)
    assert isinstance(result.missing, list)
```

---

## Completion Note

*(Agent fills this in when done)*
