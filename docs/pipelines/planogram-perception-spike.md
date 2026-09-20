# Planogram perception spike — FEAT-574

**Outcome**: inconclusive
**Date**: 2026-09-19 · **IoU threshold**: 0.5 · **Work width**: 2048 · **Evaluable photos**: 0

> Engineering gates on a small private sample — not population accuracy claims.
> Photos and annotations are private and git-ignored; this file holds aggregates only.

## Gates
| Gate | State | Detail |
|---|---|---|
| product-slot recall ≥ 0.90 on each evaluable photo | untested | 0 evaluable photo(s) |
| product-slot precision ≥ 0.90 on each evaluable photo | untested | 0 evaluable photo(s) |
| zero off-fixture observations admitted | untested | no membership module supplied |
| synthetic cases (partial shelf, absent anchors, adjacent fixture) | failed | partial_shelf: failed, absent_anchors: passed, adjacent_fixture: failed |

## Conditions exercised

Real photos: none. Required: partial_view, adjacent_fixture, absent_anchors. `repeated_skus` is not applicable at proposal level (identity is decided later).

## Per-photo, per-profile precision / recall

No evaluable private photo was supplied.

## Off-fixture proposals and admissions

Not measured (no private photos).

## Synthetic cases

| Case | Slot precision | Slot recall | Off-fixture proposals | Passed |
|---|---|---|---|---|
| full_wall | 0.86 | 1.00 | 0 | no |
| partial_shelf | 0.50 | 1.00 | 0 | no |
| absent_anchors | 1.00 | 1.00 | 0 | yes |
| adjacent_fixture | 0.67 | 1.00 | 4 | no |

## Candidate profiles evaluated

```json
[
  {
    "name": "price_tag",
    "kind": "price_tag",
    "min_width": 0.025,
    "max_width": 0.09,
    "min_height": 0.014,
    "max_height": 0.06,
    "min_aspect": 1.65,
    "max_aspect": 4.4,
    "polarity": "bright",
    "min_rectangularity": 0.75,
    "min_contrast_std": 25.0,
    "thresholds": [
      130,
      150,
      170,
      190,
      210,
      230
    ],
    "dedup_overlap": 0.5
  },
  {
    "name": "product_body",
    "kind": "product",
    "min_width": 0.06,
    "max_width": 0.3,
    "min_height": 0.08,
    "max_height": 0.45,
    "min_aspect": 0.5,
    "max_aspect": 2.5,
    "polarity": "edge",
    "min_rectangularity": 0.7,
    "min_contrast_std": 5.0,
    "thresholds": [
      130,
      150,
      170,
      190,
      210,
      230
    ],
    "dedup_overlap": 0.5
  },
  {
    "name": "product_box",
    "kind": "box",
    "min_width": 0.04,
    "max_width": 0.2,
    "min_height": 0.05,
    "max_height": 0.25,
    "min_aspect": 0.4,
    "max_aspect": 2.0,
    "polarity": "edge",
    "min_rectangularity": 0.8,
    "min_contrast_std": 5.0,
    "thresholds": [
      130,
      150,
      170,
      190,
      210,
      230
    ],
    "dedup_overlap": 0.5
  },
  {
    "name": "backlit_zone",
    "kind": "backlit",
    "min_width": 0.4,
    "max_width": 1.0,
    "min_height": 0.06,
    "max_height": 0.35,
    "min_aspect": 1.5,
    "max_aspect": 12.0,
    "polarity": "bright",
    "min_rectangularity": 0.8,
    "min_contrast_std": 5.0,
    "thresholds": [
      200,
      220,
      240
    ],
    "dedup_overlap": 0.5
  },
  {
    "name": "electronic_tag",
    "kind": "price_tag",
    "min_width": 0.03,
    "max_width": 0.12,
    "min_height": 0.02,
    "max_height": 0.08,
    "min_aspect": 1.2,
    "max_aspect": 4.0,
    "polarity": "bright",
    "min_rectangularity": 0.75,
    "min_contrast_std": 25.0,
    "thresholds": [
      130,
      150,
      170,
      190,
      210,
      230
    ],
    "dedup_overlap": 0.5
  }
]
```

## Accepted profiles

```json
[]
```

## Failures and untested conditions

- gate `slot_recall`: untested
- gate `slot_precision`: untested
- gate `off_fixture_admitted`: untested
- gate `synthetic`: failed
- synthetic case `full_wall` failed
- synthetic case `partial_shelf` failed
- synthetic case `adjacent_fixture` failed
- required conditions never exercised on a real photo: partial_view, adjacent_fixture, absent_anchors
- fewer than 3 evaluable photos (0)

## Consequence

`ProductOnShelves` keeps `perception_mode="llm_detector"` unless **Outcome** is `passed`.
