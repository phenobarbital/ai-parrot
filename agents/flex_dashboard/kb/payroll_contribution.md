# Payroll Contribution

## Definition

KPIs describing the Flex program's monthly Payroll Contribution: Worked
Hours, Payroll, P&L Revenue, and Payroll % to Revenue. Sourced from the
`hours` (`flex_hours_query_pbi`) and `finance` (`Finance_results_bi`)
datasets.

## Formula

- **Worked Hours** = `sum(hours.hours)`. Pay-code and cost-center
  filterable. `finance.Total Hours` is a related field used ONLY as an
  independent FTE cross-check — it is never the source of Worked Hours.
- **Payroll** = `sum(finance.Payroll)`, by month.
- **P&L Revenue** = `sum(finance.Revenue)`, by month.
- **Payroll % to Revenue** = `sum(Payroll) / sum(Revenue)`. The denominator
  is **Revenue ALONE** — never `Revenue + PC Revenue`. This is a resolved,
  pinned formula (spec §2 Q&A); do not substitute a different denominator
  even though `PC Revenue` is a sibling column in the same dataset.

## Source columns

- `hours` (`flex_hours_query_pbi`): `month_start`, `month_end`, `program`,
  `pay_code`, `cost_center`, `hours`, `wages`.
- `finance` (`Finance_results_bi`): `project`, `month` (month-end date),
  `Revenue`, `PC Revenue`, `Payroll`, and other P&L columns (currency
  strings).

## Normalization rules

- `finance`'s `Revenue`/`Payroll`/etc. arrive as formatted currency strings
  (e.g. `"$137,456.85"`, negatives `"-$44,621.24"`) — parsed via
  `agents/flex_dashboard/normalize.parse_currency` before any arithmetic.
- Month grain: `finance.month` is a month-END date (e.g. `"2025-10-31"`);
  `hours.month_start` is a month-START date (e.g. `"2025-10-01"`). Both
  resolve to the same canonical `"2025-10"` period key via
  `normalize.month_period`.

## Filters

Per-section filter rule: a filter only applies to sections whose dataset
carries that column.

- Worked Hours / Pay Code sections (`hours` dataset): `month`, `pay_code`,
  `cost_center`.
- Payroll / Revenue / Payroll % sections (`finance` dataset): `month` only
  — `finance` has no `pay_code`/`cost_center` column, so those filters
  never reach it.

## Worked example

From the sample rows (`sdd/state/FEAT-517/source.md`):

- `finance` row: `month="2025-10-31"`, `Revenue="$137,456.85"`,
  `Payroll="$20,682.27"`.
- `hours` row: `month_start="2025-10-01"`, `hours=30.199996`.

Computed:

- Worked Hours (2025-10) = `30.199996`.
- Payroll (2025-10) = `20682.27`.
- P&L Revenue (2025-10) = `137456.85`.
- Payroll % to Revenue (2025-10) = `20682.27 / 137456.85` = `0.15046372734425384`
  (≈ 15.05%).
