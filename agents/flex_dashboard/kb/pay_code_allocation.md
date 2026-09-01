# Pay Code Hours / Worked Hours by Pay Code Allocation

## Definition

Two related sections over the `hours` dataset (`flex_hours_query_pbi`):
Pay Code Hours (a per-pay-code hours listing) and Worked Hours by Pay Code
Allocation (each pay_code's share of total worked hours).

## Formula

- **Pay Code Hours** — for each `pay_code`, `sum(hours)` (optionally
  narrowed by `month`/`cost_center`, or to a single `pay_code`).
- **Worked Hours by Pay Code Allocation** — for each `pay_code`:
  `share_pct = sum(hours for that pay_code) / sum(hours, all pay codes) * 100`
  (optionally narrowed by `month`/`cost_center`; NOT by a single `pay_code`,
  since allocation is inherently a breakdown ACROSS pay codes).

## Source columns

`hours` (`flex_hours_query_pbi`): `month_start`, `month_end`, `program`,
`pay_code`, `cost_center`, `hours`, `wages`.

## Normalization rules

Month grain: `month_start` resolves to the canonical `"YYYY-MM"` period key
via `normalize.month_period(source="hours")`. `hours`/`wages` are already
numeric — no currency parsing needed for this dataset.

## Filters

Per-section filter rule:

- Pay Code Hours: `month`, `pay_code`, `cost_center` — all supported by the
  `hours` dataset.
- Worked Hours by Pay Code Allocation: `month`, `cost_center` only (a
  `pay_code` filter would make the "allocation across pay codes" question
  meaningless).

## Worked example

From the sample row (`sdd/state/FEAT-517/source.md`):

```json
{"month_start": "2025-10-01", "pay_code": "Admin Time", "cost_center": "Flex", "hours": 30.199996}
```

Pay Code Hours (2025-10): `Admin Time` = `30.199996`.

Worked Hours by Pay Code Allocation (2025-10): with only this one sample
row available, `Admin Time` is the sole pay code present, so its share is
`30.199996 / 30.199996 * 100 = 100.0%`. With additional pay codes present
(e.g. a second `"Field Time"` row), each pay code's share is its own hours
divided by the sum of ALL pay codes' hours in the filtered window,
expressed as a percentage.
