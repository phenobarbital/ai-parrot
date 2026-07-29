---
type: Wiki Overview
title: 'TASK-1025: Fit/Gap Report (Phase 2)'
id: doc:sdd-tasks-completed-task-1025-fit-gap-report-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Agents need to classify business requirements against Odoo's capabilities
  to
---

# TASK-1025: Fit/Gap Report (Phase 2)

**Feature**: FEAT-147 — Evaluate Odoo MCP Toolkit
**Spec**: `sdd/specs/evaluate-odoo-mcp-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1013, TASK-1018
**Assigned-to**: unassigned

---

## Context

Agents need to classify business requirements against Odoo's capabilities to
determine what's standard, what needs configuration, and what requires custom
development. This task adds a heuristic fit/gap classifier.

Implements spec §3 Module 13: Fit/Gap Report.

---

## Scope

- Add `fit_gap_report` async method to `OdooToolkit`
- Implement heuristic keyword-based requirement classification into buckets:
  `standard`, `configuration`, `studio`, `custom_module`, `avoid`, `unknown`
- Optionally query live Odoo (via `schema_catalog` from TASK-1018) for installed
  modules and available models to improve classification confidence
- Produce summary counts per bucket and recommended follow-up Odoo calls
- Decorate with `@tool_schema(FitGapReportInput)`
- Return `FitGapResult` envelope

**NOT in scope**: `business_pack_report`, `scan_addons_source`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/odoo/toolkit.py` | MODIFY | Add `fit_gap_report` and classification helpers |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .models.inputs import FitGapReportInput   # TASK-1013
from .models.envelopes import FitGapResult     # TASK-1013
```

### Existing Signatures to Use
```python
# TASK-1018 adds:
async def schema_catalog(self, query=None, models=None, include_fields=False, limit=50) -> SchemaCatalogResult:
async def get_odoo_profile(self, include_modules=True, module_limit=100) -> OdooProfileResult:
```

### Does NOT Exist
- ~~`OdooToolkit.fit_gap_report()`~~ — must be created

---

## Implementation Notes

### Classification Heuristic
Each requirement is a dict with at minimum a `"description"` key. The classifier:

1. Checks for keyword matches against known Odoo standard features:
   - Sales keywords → `standard` if `sale` module exists
   - CRM keywords → `standard` if `crm` module exists
   - Inventory keywords → `standard` if `stock` module exists
   - etc.
2. Configuration indicators: "configure", "setting", "parameter", "threshold",
   "workflow rule", "automated action" → `configuration`
3. Studio indicators: "drag and drop", "form builder", "custom field", "custom view"
   → `studio`
4. Anti-pattern indicators: "real-time sync", "custom ORM", "bypass security" → `avoid`
5. If live metadata available: check if mentioned models/modules exist → improves
   confidence from `unknown` to `standard`/`custom_module`
6. Default: `unknown`

### Live Evidence (optional)
When the toolkit is connected, call `get_odoo_profile` to get installed modules and
`schema_catalog` to check available models. This is optional — the tool works fully
offline with the heuristic alone.

### Key Constraints
- `requirements` is a `list[dict[str, Any]]` — each must have at least `"description"`
- Classification is inherently approximate — always label `"unknown"` when confidence is low
- Return recommended follow-up calls (e.g., "Run `schema_catalog(query='stock')` to check")

---

## Acceptance Criteria

- [ ] "Track sales orders by customer" classified as `standard`
- [ ] "Build custom blockchain integration" classified as `custom_module`
- [ ] Produces summary: `{"standard": 3, "custom_module": 1, "unknown": 2, ...}`
- [ ] With live models, improves classification of previously `unknown` requirements
- [ ] Returns `FitGapResult` envelope with `recommended_calls`

---

## Test Specification

```python
@pytest.mark.asyncio
async def test_fit_gap_standard(odoo_toolkit):
    result = await tk.fit_gap_report(requirements=[
        {"description": "Track sales orders by customer"},
    ])
    assert result.requirements[0].get("classification") == "standard" or \
           result.requirements[0].get("bucket") == "standard"

@pytest.mark.asyncio
async def test_fit_gap_custom(odoo_toolkit):
    result = await tk.fit_gap_report(requirements=[
        {"description": "Custom blockchain ledger integration with Odoo"},
    ])
    req = result.requirements[0]
    assert req.get("classification") in ("custom_module", "unknown")
```

---

## Completion Note

*(Agent fills this in when done)*
