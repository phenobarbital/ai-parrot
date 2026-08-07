# `narrative_facts` contract

This documents the **actual shipped output** of the `narrative_facts`
transformer (`parrot.outputs.a2ui.recipes.library`, FEAT-420 Module 1) — the
authority for this skill. Every field below is deterministic: no clocks, no
I/O, no randomness. Numeric values are already 2dp-rounded.

```
{
  "headline": {
      "rev_state": "behind" | "ahead",
      "rev_direction": "narrowing" | "widening" | "flat",
      "ebitda_direction": "improved" | "worsened" | "held_steady",
      "both_improving": bool,
      "both_worsening": bool,
      "diverging": bool,
      "first_label": str,
      "last_label": str
  },
  "top_driver": {
      "division": str,
      "project": str,
      "ebitda_variance": float,
      "trend": float | null,
      "urgency": "immediate" | "confirm_trend" | "check_timing"
  } | null,
  "division_reads": [
      {
        "division": str,
        "kind": "on_track" | "spread" | "concentrated" | "offset_by",
        "named": [str, ...],
        "offsetter": str | null
      },
      ...
  ],
  "watch": [
      {
        "division": str,
        "project": str,
        "ebitda_variance": float,
        "trend": float | null,
        "trend_basis": "since_first" | "new_this_period"
      },
      ...
  ],
  "bright": [ ... same shape as "watch" ... ],
  "n_snapshots": int
}
```

## Field meanings

### `headline`

- `rev_state` — is the LATEST snapshot's revenue behind or ahead of budget.
- `rev_direction` — is the revenue-variance gap narrowing, widening, or flat
  across the snapshots.
- `ebitda_direction` — has EBITDA variance improved, worsened, or held
  steady across the snapshots.
- `both_improving` / `both_worsening` — true only when revenue AND EBITDA
  move the same favorable/unfavorable way. `diverging` is true otherwise
  (including the flat/held_steady case) — say "mixed signals" rather than
  claiming a clean improvement or worsening when `diverging` is true.
- `first_label` / `last_label` — the first and last snapshot identifiers
  (opaque strings — do not reformat as a date unless they already look like
  one).

### `top_driver` (may be `null` — omit the "Key driver" and
"Recommendation" sections entirely when it is)

- The single worst (most negative EBITDA-variance) project across all
  divisions at the latest snapshot.
- `trend` — the change in this project's EBITDA variance from the first to
  the latest snapshot. `null` means the project is new at the latest
  snapshot — say "new this period", never a number.
- `urgency` — derived from `trend`'s sign: `immediate` (still worsening),
  `confirm_trend` (improving — verify it holds), `check_timing` (flat or
  `null` — no trend to act on yet).

### `division_reads[]`

One entry per division. `kind` is one of:

- `on_track` — no materially negative project, and the division's net
  EBITDA variance is non-negative.
- `spread` — no materially negative project, but the division's net EBITDA
  variance IS negative (the shortfall is spread thin, not concentrated).
- `concentrated` — has a materially negative project(s) AND the division's
  net EBITDA variance is negative — the shortfall traces to those named
  projects.
- `offset_by` — has a materially negative project(s) but the division's net
  EBITDA variance is non-negative — another project is offsetting it.
  `offsetter` names that offsetting project (the division's best-performing
  project by EBITDA variance). `offsetter` is `null` for every OTHER kind.

`named` lists the materially negative projects behind a `concentrated` or
`offset_by` read (capped at 2 by default — a param, not a fixed constant).
"Materially negative" means EBITDA variance below the materiality threshold
(default `-5000`, also a param).

### `watch[]` / `bright[]`

The overall worst/best-performing projects (not scoped to `top_driver`'s
division). Same shape and `trend`/`trend_basis` semantics as `top_driver`.
`trend_basis` is `since_first` when a trend value exists, `new_this_period`
when it is `null` — there is no day-over-day figure available, only a
first-vs-latest one, so never phrase a `watch`/`bright` trend as
"yesterday" or "today".

### `n_snapshots`

How many snapshots were combined to produce this analysis. `1` means a
single-snapshot read — in that case `rev_direction`/`ebitda_direction` are
always `flat`/`held_steady` and every `trend` is `null` (nothing to compare
against); say so plainly rather than describing a trend that does not
exist.
