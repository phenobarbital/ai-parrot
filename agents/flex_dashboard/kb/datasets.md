# Flex Datasets Reference

## Definition

The six QuerySource slugs the `flex_dashboard` agent registers on its
`DatasetManager`, their stable aliases, grains, and known data quirks. The
aliases below are FROZEN (spec §2) — every transformer hard-codes its
input frame key to these exact names.

## Formula

Alias resolution (slug -> alias -> content):

| Alias | Slug | Content |
|---|---|---|
| `msl` | `flex_msl_brian_bi` | Master Store List (district/region/market/account/store, lat/lon) |
| `finance` | `Finance_results_bi` | Monthly P&L per project (currency strings, `month` month-end) |
| `hours` | `flex_hours_query_pbi` | Hours/wages by month, program, pay_code, cost_center |
| `employees` | `flex_empolyees_brian_bi` | Employee roster with lat/lon, Flex Type, tenure |
| `region_utilization` | `fm_regions_avg_employees_html` | Regional monthly employee utilization (BOP/EOP dates) |
| `rep_utilization` | `fm_rep_utilization` | Rep utilization by region/state/category (has `catagory` typo column) |

## Source columns

See `payroll_contribution.md`, `pay_code_allocation.md`,
`rep_utilization.md`, and `proximity_staffing.md` for the per-KPI column
lists. In brief:

- `msl`: `district_name`, `region_name`, `market_name`, `account_name`,
  `store_name`, `latitude`, `longitude`, `city`, `state_code`.
- `finance`: `project`, `month`, `Revenue`, `PC Revenue`, `EBITDA`,
  `Payroll`, `Travel and Expenses`, `Program Overhead Allocation`,
  `Other Related Expenses`, `Total Hours`, `FTE`, `Visits`.
- `hours`: `month_start`, `month_end`, `program`, `pay_code`,
  `cost_center`, `hours`, `wages`.
- `employees`: `display_name`, `start_date`, `job_code_title`,
  `legal_city`, `legal_state`, `zipcode`, `latitude`, `longitude`,
  `Flex Employees`, `Flex Type`, tenure fields.
- `region_utilization`: `BOP Date`, `EOP Date`, `FM Region`,
  `State Code`, `State`, `Category`, `Employees Worked`,
  `Average Active Employees`, `Flex Employees`, `Employee Utilization`.
- `rep_utilization`: `bop_date`, `eop_date`, `region`, `state`,
  `catagory`, `hours_worked`, `work_shifts`, `employees_worked`,
  `average_active`.

## Normalization rules

Three quirks, ALL handled centrally by
`agents/flex_dashboard/normalize.py` — never inline in a transformer:

1. **Currency strings** — `finance`'s money columns arrive as formatted
   strings (`"$137,456.85"`, negatives `"-$44,621.24"`), parsed by
   `parse_currency` / `normalize_currency_columns`.
2. **Three date-grain conventions** — `finance.month` (month-end date),
   `hours.month_start` (month-start date), and the `fm_*` datasets'
   `BOP Date`/`bop_date` (period-start date) — all resolved to one
   canonical `"YYYY-MM"` `month` column via `month_period`.
3. **Header casing / typos** — `fm_rep_utilization`'s `catagory` typo
   column, and `fm_regions_avg_employees_html` / `flex_empolyees_brian_bi`'s
   Title/Space-Case headers, are canonicalized to snake_case via
   `canonicalize_columns`.

## Filters

Filters are **per-section** (proposal U1): a filter only applies to
sections whose dataset actually carries that column.

| Filter | Applies to (dataset) |
|---|---|
| `month` | `finance`, `hours`, `region_utilization`, `rep_utilization` (all, after `month_period`) |
| `pay_code` | `hours` only |
| `cost_center` | `hours` only |
| `flex_type` | `employees` only |
| `category` | `region_utilization`, `rep_utilization` only (after canonicalization) |
| `radius_miles` / `nearest_n` | Proximity Staffing (`msl` + `employees`) only |

A `flex_type` or `category` filter must never reach or alter a
finance-only section (`payroll_by_month`, `revenue_by_month`,
`payroll_pct_by_month`) — those transformers only ever read the `month`
param.

## Worked example

Resolving `hours` end to end: slug `flex_hours_query_pbi` -> alias
`hours` -> sample row `{"month_start": "2025-10-01", "pay_code": "Admin Time",
"cost_center": "Flex", "hours": 30.199996}` -> after `month_period(source="hours")`
the row carries `month="2025-10"`, ready for `worked_hours_by_month` /
`pay_code_hours` / `pay_code_allocation` to group over.
