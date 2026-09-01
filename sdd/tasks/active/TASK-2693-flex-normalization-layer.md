# TASK-2693: Flex normalization layer (currency, month grain, column canonicalization)

**Feature**: FEAT-491 — Flex A2UI Dashboard Agent
**Spec**: `sdd/specs/flex-agent-infographic-a2ui.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. The six Flex datasets arrive dirty: `Finance_results_bi`
currency columns are formatted strings (`"$137,456.85"`, `"-$44,621.24"`),
three date-grain conventions coexist (finance `month` = month-end date,
hours `month_start`/`month_end`, fm_* `BOP Date`/`EOP Date` and
`bop_date`/`eop_date`), and `fm_rep_utilization` ships a `catagory` typo
column plus header-casing differences vs `fm_regions_avg_employees_html`.
ALL canonicalization must live here — transformers (TASK-2694) never inline
it (spec §7 Known Risks).

---

## Scope

- Create `agents/flex_dashboard/__init__.py` (package marker).
- Implement `agents/flex_dashboard/normalize.py` with **pure functions**:
  - `parse_currency(value: str | float) -> float` — `"$137,456.85"` → 137456.85,
    `"-$44,621.24"` → -44621.24, `"$0.00"` → 0.0; passthrough for numerics;
    NaN-safe.
  - `normalize_currency_columns(df, columns) -> pd.DataFrame`.
  - `month_period(df, *, source: str) -> pd.DataFrame` — adds a canonical
    `month` period column (`YYYY-MM`) from each convention: finance
    month-end `month`, hours `month_start`, fm `BOP Date`/`bop_date`.
  - `canonicalize_columns(df, *, source: str) -> pd.DataFrame` — rename map:
    `catagory`→`category`, `FM Region`→`region`, `State Code`→`state`,
    `Employees Worked`→`employees_worked`,
    `Average Active Employees`→`average_active`,
    `Employee Utilization`→`employee_utilization`, etc. (snake_case output).
- Create the shared synthetic-frames fixture `flex_frames` shaped EXACTLY
  like the sample rows in `sdd/state/FEAT-517/source.md` (currency strings,
  the three date conventions, the `catagory` typo included) in
  `packages/ai-parrot/tests/unit/bots/conftest.py` (or a local conftest for
  the flex tests).
- Write unit tests: `test_parse_currency`, `test_month_alignment`,
  `test_column_canonicalization` (spec §4 table).

**NOT in scope**: transformers (TASK-2694), agent class (TASK-2696), any
network/QuerySource access.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/flex_dashboard/__init__.py` | CREATE | package marker |
| `agents/flex_dashboard/normalize.py` | CREATE | pure normalization functions |
| `packages/ai-parrot/tests/unit/bots/test_flex_dashboard_normalize.py` | CREATE | unit tests |
| `packages/ai-parrot/tests/unit/bots/conftest.py` | CREATE or MODIFY | `flex_frames` fixture (six synthetic frames) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import pandas as pd   # project-wide dependency
import numpy as np    # project-wide dependency
```
No parrot imports are needed — this module is pure pandas by design.

### Input shapes (from `sdd/state/FEAT-517/source.md` sample rows — authoritative)
- `finance` (`Finance_results_bi`): `project`, `month` (month-end date str),
  `Revenue`/`PC Revenue`/`EBITDA`/`Payroll`/`Travel and Expenses`/
  `Program Overhead Allocation`/`Other Related Expenses` (currency **strings**),
  `Total Hours` (float), `FTE` (float), `Visits` (int).
- `hours` (`flex_hours_query_pbi`): `month_start`, `month_end`, `program`,
  `pay_code`, `cost_center`, `hours` (float), `wages` (float).
- `msl` (`flex_msl_brian_bi`): `district_name`, `region_name`, `market_name`,
  `account_name`, `store_name`, `latitude`, `longitude`, `city`, `state_code`.
- `employees` (`flex_empolyees_brian_bi`): `display_name`, `start_date`,
  `job_code_title`, `legal_city`, `legal_state`, `zipcode`, `latitude`,
  `longitude`, `Flex Employees`, `Flex Type`, `Years/Months/Days of Service`.
- `region_utilization` (`fm_regions_avg_employees_html`): `BOP Date`,
  `EOP Date`, `FM Region`, `State Code`, `State`, `Category`,
  `Employees Worked`, `Average Active Employees`, `Flex Employees`,
  `Employee Utilization` (float ratio).
- `rep_utilization` (`fm_rep_utilization`): `bop_date`, `eop_date`, `region`,
  `state`, **`catagory`** (typo, real column name), `hours_worked`,
  `work_shifts`, `employees_worked`, `average_active`.

### Does NOT Exist
- ~~a shared normalization helper in `parrot/`~~ — nothing in core does
  currency-string parsing for these datasets; this module IS that layer.
- ~~a `category` column in `fm_rep_utilization`~~ — the raw column is
  `catagory`; only the canonicalized output has `category`.

---

## Implementation Notes

### Key Constraints
- Pure functions, no I/O, no logging side effects required (module-level
  functions, not a class).
- Deterministic: same input frame → same output frame (recipe replay
  depends on it).
- Google-style docstrings + strict type hints (project standard).
- Never mutate the input frame in place — return copies.

### References in Codebase
- `sdd/state/FEAT-517/source.md` — authoritative sample rows.
- `sdd/specs/flex-agent-infographic-a2ui.spec.md` §2 (alias table), §7.

---

## Acceptance Criteria

- [ ] `parse_currency` handles positive, negative, zero, and non-string inputs.
- [ ] `month_period` aligns all three date conventions to the same `YYYY-MM` key.
- [ ] `canonicalize_columns` maps `catagory`→`category` and fm header variants to snake_case.
- [ ] `flex_frames` fixture provides all six aliases with spec-faithful dirtiness.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/bots/test_flex_dashboard_normalize.py -v`
- [ ] No linting errors: `ruff check agents/flex_dashboard/`

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/test_flex_dashboard_normalize.py
# IMPORT MECHANICS (verified): agents/ is gitignored by default and a plain
# `import agents.flex_dashboard` resolves inconsistently from worktrees.
# Load by file path with importlib.util, copying the _load_finance_reporter()
# helper in test_finance_reporter_descriptors.py (lines 1-21 explain why).

def test_parse_currency():
    assert parse_currency("$137,456.85") == 137456.85
    assert parse_currency("-$44,621.24") == -44621.24
    assert parse_currency("$0.00") == 0.0

def test_month_alignment(flex_frames):
    ...  # finance month-end, hours month_start, fm BOP → same "2025-10" key

def test_column_canonicalization(flex_frames):
    ...  # catagory → category; "FM Region" → region
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/flex-agent-infographic-a2ui.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
