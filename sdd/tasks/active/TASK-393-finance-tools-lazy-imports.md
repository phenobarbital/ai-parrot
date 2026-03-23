# TASK-393: Financial Tools Lazy Imports

**Feature**: runtime-dependency-reduction
**Spec**: `sdd/specs/runtime-dependency-reduction.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-386, TASK-387
**Assigned-to**: unassigned

---

## Context

Financial analysis tools import `ta-lib` and `pandas-datareader` at module level. `ta-lib` requires a C library (`libta-lib-dev`) making it one of the hardest dependencies to install. These are niche tools used only by financial analysis agents.

Implements: Spec Module 8 — Financial Tools Lazy Imports.

---

## Scope

- Convert top-level imports to `lazy_import()` in:
  - `parrot/tools/technical_analysis.py` — ta-lib → `lazy_import("talib", package_name="TA-Lib", extra="finance")`
  - Any other files that import pandas-datareader → `lazy_import("pandas_datareader", extra="finance")`
- Search for other files importing `ta`, `talib`, `pandas_datareader` and convert them.

**NOT in scope**: yfinance (in agents extra, not core).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/technical_analysis.py` | MODIFY | Lazy-import ta-lib, pandas-datareader |
| Other files with ta-lib/pandas-datareader imports | MODIFY | Lazy-import as needed |

---

## Implementation Notes

### Key Constraints
- `talib` module name vs `TA-Lib` pip name — use `package_name` param
- `pandas_datareader` module name vs `pandas-datareader` pip name
- ta-lib requires `libta-lib-dev` system package — error message should mention this

---

## Acceptance Criteria

- [ ] Technical analysis tools importable without ta-lib/pandas-datareader
- [ ] Missing dep raises: `pip install ai-parrot[finance]`
- [ ] All functionality works when deps are installed
- [ ] All existing tests pass with deps installed

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-386 and TASK-387 are completed
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-393-finance-tools-lazy-imports.md`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
