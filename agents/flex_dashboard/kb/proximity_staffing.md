# Proximity Staffing

## Definition

Compares the Master Store List (`flex_msl_brian_bi`) against the Employee
roster (`flex_empolyees_brian_bi`) by geographic proximity: for each store,
the nearest-N employees and a coverage count within a radius threshold.

## Formula

For each store in `msl`:

1. Compute the great-circle (haversine) distance in miles from the store's
   `(latitude, longitude)` to every employee's `(latitude, longitude)`.
2. **Nearest-N employees** = the `nearest_n` (default `3`) closest
   employees by distance, regardless of the radius threshold.
3. **Coverage count** = the number of employees whose distance to the
   store is `<= radius_miles` (default `50`).

Output shape: a store map layer, an employee map layer, and a per-store
coverage table (`nearest_employees` + `employees_within_radius`).

Haversine distance (miles), Earth radius `R = 3958.8`:

```
a = sin²(Δφ/2) + cos(φ1)·cos(φ2)·sin²(Δλ/2)
c = 2·atan2(√a, √(1−a))
distance = R · c
```

## Source columns

- `msl` (`flex_msl_brian_bi`): `district_name`, `region_name`,
  `market_name`, `account_name`, `store_name`, `latitude`, `longitude`,
  `city`, `state_code`.
- `employees` (`flex_empolyees_brian_bi`): `display_name`, `latitude`,
  `longitude`, `Flex Type`, plus tenure fields.

## Normalization rules

`employees`' `Flex Type` (and other Title/Space-Case headers) are
canonicalized to `flex_type` (snake_case) via
`normalize.canonicalize_columns(source="employees")` before any
`flex_type` filter is applied. Coordinates are used as-is (already
numeric, no currency/date handling needed).

## Filters

- `radius_miles` (default `50`) — the coverage-count threshold.
- `nearest_n` (default `3`) — how many nearest employees to list per store.
- `flex_type` — narrows the employee layer (and therefore the coverage
  computation) to a single Flex Type; never applies to the store layer,
  which has no `flex_type` column.

## Worked example

From the sample rows (`sdd/state/FEAT-517/source.md`):

- Store: `T-Mobile 3SFD Norridge IL`, `latitude=41.95535`,
  `longitude=-87.80886` (Norridge, IL).
- Employee: `Abby Halladay`, `latitude=39.9222285`, `longitude=-75.414058`
  (Media, PA).

Haversine distance between these two points ≈ `661.38` miles (computed via
the formula above, `R = 3958.8`). With only this single employee sample
row, that single-store, single-employee pair IS the entire nearest-N list
for `T-Mobile 3SFD Norridge IL` when `nearest_n >= 1`, and — since
`661.38 > 50` — `employees_within_radius = 0` for the default radius.
