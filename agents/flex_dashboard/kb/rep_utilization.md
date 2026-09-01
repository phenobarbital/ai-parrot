# Rep (Representative) Utilization

## Definition

Utilization of Flex representatives by region/category/month, RECOMPUTED
from `fm_rep_utilization`. `fm_regions_avg_employees_html`'s precomputed
`Employee Utilization` column is surfaced only as a cross-check, never as
the source of truth (spec §2 resolved Q&A).

## Formula

**Rep Utilization** = `employees_worked / average_active`, recomputed per
region/category/month from `rep_utilization` (`fm_rep_utilization`).

The `region_utilization` (`fm_regions_avg_employees_html`) dataset's
precomputed `Employee Utilization` column is attached alongside the
recomputed value, when a matching (region, category, month) row exists, as
`cross_check_utilization` — a validation signal, not the authoritative
number. If the two diverge materially, trust the recomputed value and flag
the discrepancy; never silently prefer the precomputed column.

## Source columns

- `rep_utilization` (`fm_rep_utilization`): `bop_date`, `eop_date`,
  `region`, `state`, `catagory` (raw typo — see Normalization rules),
  `hours_worked`, `work_shifts`, `employees_worked`, `average_active`.
- `region_utilization` (`fm_regions_avg_employees_html`): `BOP Date`,
  `EOP Date`, `FM Region`, `State Code`, `State`, `Category`,
  `Employees Worked`, `Average Active Employees`, `Flex Employees`,
  `Employee Utilization`.

## Normalization rules

- `fm_rep_utilization` ships a **`catagory`** typo column — canonicalized
  to `category` via `normalize.canonicalize_columns(source="rep_utilization")`.
  The raw column name is genuinely `catagory`; this is not a documentation
  error.
- `fm_regions_avg_employees_html` header variants (`FM Region`,
  `State Code`, `Employees Worked`, `Average Active Employees`,
  `Employee Utilization`, ...) are canonicalized to snake_case via
  `normalize.canonicalize_columns(source="region_utilization")`.
- Both datasets' `BOP Date`/`bop_date` columns resolve to the canonical
  `"YYYY-MM"` period key via `normalize.month_period(source="fm")`.

## Filters

`month`, `category` — both datasets carry `region`/`category`/month
columns after canonicalization, so these filters apply to both the
recomputed and the cross-check side of this section.

## Worked example

From the sample rows (`sdd/state/FEAT-517/source.md`):

- `rep_utilization` row: `region="CA"`, `catagory="Flex"`,
  `employees_worked=12`, `average_active=63`, month `2026-05`.
  Rep Utilization = `12 / 63 = 0.19047619047619047` (≈ 19.05%).
- `region_utilization` row: `FM Region="CA"`, `Category="Flex"`,
  `Employees Worked=11`, `Average Active Employees=75.5`, month `2026-03`.
  Precomputed `Employee Utilization = 11 / 75.5 = 0.1456953642384106`
  (matches the dataset's own stated value exactly), illustrating the
  cross-check computation — note this sample row is a DIFFERENT month
  (`2026-03` vs `2026-05`) than the `rep_utilization` sample, so in this
  particular pair of samples there is no matching (region, category,
  month) key and `cross_check_utilization` would be `None` for that row.
