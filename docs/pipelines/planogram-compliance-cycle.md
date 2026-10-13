# Planogram compliance cycle (perceive → identify → compare)

## Overview

All six registered types (`product_on_shelves`, `ink_wall`, `endcap_backlit_multitier`,
`endcap_no_shelves_promotional`, `graphic_panel_display`, and `product_counter`) use one
three-stage contract. The pipeline retains the untouched, full-resolution image for the whole
run: OpenCV-first perception proposes observed geometry, OCR and a vision LLM identify observed
areas, and deterministic comparison evaluates the configured definition. `CycleContext` is
run-owned and holds the executor, OCR reader, reference bank, definition, bindings, layout,
errors, and image state.

## Stage contracts

| Stage | Contract | Behaviour |
|---|---|---|
| Perceive | `perceive(image, image_id, ctx)` | Builds source-pixel shapes, zones, rows, and slots from the configured profile. |
| Fallback | pipeline orchestrator | At most once per image, below `min_usable_shapes`; it uses the generic detector prompt, rebuilds geometry, preserves `cv`, `llm`, or `mixed` provenance, and records failed or empty fallback output as errors. |
| Identify | `identify(image, perception, ctx)` | Uses `full_image`, `strips`, or `slots`, adds own-box OCR readings, reference attachments on initial and repair calls, and neutral rule evidence. |
| Compare | `compare(perceptions, identifications, ctx)` | Performs no I/O: it registers observations, evaluates rules, scores units, and projects compliance. |

An image failure is isolated. If every image fails, the result is inconclusive with zero scores,
coverage, and evidence quality; it is never compliant.

## Layout profiles

Put overrides in `PlanogramConfig.planogram_config["layout_profile"]`; no new database column
is required. The pipeline recursively merges nested model values with the type's fresh default
profile, replaces lists atomically, and rejects unknown keys. The top-level `perception_mode`
alias is accepted only when it does not contradict `layout_profile.perception_mode`.

| Field group | Settings |
|---|---|
| Geometry | `shape_profiles`, `anchor_rule`, `fill_gaps`, `untagged_bottom_row`, `min_usable_shapes`, `min_row_items`, `max_row_slope`, `work_width`, `substrip_max_slots` |
| Identification | `identify_strategy`, `descriptor_fields`, `required_descriptor_fields`, `ocr_targets`, `ocr_batch_size` |
| Perception | `perception_mode` (`cv` by default, or `llm_detector`) |
| Reporting | `reporting.product_label` (`display_name` or `product`), `reporting.slot_presence`, `reporting.misplaced_min_confidence` |
| References | `references.enabled`, `selection` (`all` or `by_brand`), provisional `max_per_call` default `5`, and `brand_by_reference` |
| Zones | `zone_selectors` with `zone_id`, optional profile/kind, ordinal, or normalized region |

Selectors resolve observed zones only. Repeated zone kinds need selectors; an ambiguous or
unassessed zone does not become a passing observation.

| Type | Identify strategy | Fallback threshold | Profile emphasis |
|---|---:|---:|---|
| `ink_wall` | `strips` | 8 | price tags, tag-below anchors, gap fill |
| `product_on_shelves` | `full_image` | 3 | product, box, tag, and fact-tag candidates |
| `endcap_backlit_multitier` | `strips` | 3 | body, box, tag, and zone candidates |
| `endcap_no_shelves_promotional` | `full_image` | 1 | zones and configured promotional rules |
| `graphic_panel_display` | `full_image` | 1 | zones and graphic/text/illumination rules |
| `product_counter` | `full_image` | 1 | product bodies, background, and information-label zones |

## Reporting policy and `products_found`

`ReportingPolicy` controls how products are labelled and whether slot presence is reported. It resolves in this order, each step overriding the previous one: the policy defaults, the type's layout profile, `planogram_config["layout_profile"]["reporting"]`, and finally `slots_definition["meta"]["reporting"]`. Unknown keys are rejected.

| Type | `product_label` | `slot_presence` |
|---|---|---|
| `ink_wall` | `product` | on |
| `endcap_backlit_multitier`, `product_on_shelves`, `product_counter`, `graphic_panel_display` | `display_name` | on |
| `endcap_no_shelves_promotional` | `display_name` | off (zone-only definitions) |

A `products_found` entry represents a slot that is expected to contain a product. It carries the following fields:

- `shelf_id`, `shelf_level`, `slot`, `position` — the slot's location
- `facing_ids` — the facing identifiers that belong to this slot
- `model`, `sku`, `brand`, `display_name` — the product's identity
- `found` — a tri-state flag, resolved across the slot's facings (any found facing wins, then any undecided facing, otherwise false). `null` means "not visible / not assessed / conflict" and is never an absent entry:
  - `true` if at least one facing is found (MATCH, VARIANT_UNRESOLVED, INFERRED_PRESENT, or MISPLACED with confidence >= `misplaced_min_confidence`)
  - `null` if no facing is found and at least one has no deciding view (NOT_VISIBLE, NOT_ASSESSED, CONFLICT, OCCUPIED_UNASSIGNED, or MISPLACED below the confidence threshold)
  - `false` if every facing is MISMATCH or EMPTY
- `misplaced` — `true` if the slot is found and the representative facing's observation is MISPLACED with confidence >= `misplaced_min_confidence`
- `status` and `misplaced` come from the representative facing: the first facing whose own `found` value equals the slot's
- `confidence` — the representative facing's observation confidence; `null` when it has no deciding view or no observations (it can be populated while `found` is `null`, e.g. a low-confidence MISPLACED)
- `facings` — the total number of facings in the slot
- `facings_found` — the number of facings that are found
- `observed` — the observed identity of the slot (e.g., brand or model), or `null` if not observed

To disable slot presence reporting, set `reporting.slot_presence = false` either in the planogram config's `layout_profile.reporting` or in `slots_definition["meta"]["reporting"]`:

```json
{
  "planogram_config": {
    "layout_profile": {
      "reporting": {
        "slot_presence": false
      }
    }
  }
}
```

or

```json
{
  "slots_definition": {
    "meta": {
      "reporting": {
        "slot_presence": false
      }
    }
  }
}
```

## OCR and references

Local OCR auto-enables when the optional planogram extra is installed; pass `enabled_ocr=False`
to disable it. OCR reads each target's own source-pixel box. No OCR reading, or an unavailable
OCR engine, is not evidence that a slot is empty; the vision model still assesses occupancy.

`reference_images` accepts a path, list of paths, or PIL image per catalogue key. The bank
flattens sorted catalogue keys and stable list order, loads and encodes each valid image once per
run, and labels them `ref-0001`, `ref-0002`, and so on. `all` selects the stable capped set;
`by_brand` uses observed brand/OCR evidence. Unreadable references and selection decisions are
diagnostics. References never state an expected position, and the optional vision-response cache
is invalidated when their attachment bytes change.

## Type hook contract

Every `AbstractPlanogramType` implements all four members:

1. `default_layout_profile()` returns a fresh `LayoutProfile`.
2. `perceive()` composes `perceive_image()` with type-specific observed geometry.
3. `identify()` composes `identify_image()` with the resolved profile.
4. `compare()` composes `compare_observations()` with deterministic projection.

`validate_contract()` rejects a missing member with `TypeError` and rejects a missing
`slots_definition` with a `ValueError` that points to the [migration runbook](planogram-cycle-migration.md).
There is no alternative pipeline contract.

## Adding a planogram type

1. Define a fresh default `LayoutProfile` with data-only shape profiles, anchoring, strategy,
   descriptor vocabulary, references, and zone selectors.
2. Implement `perceive()` by calling `perceive_image()`; keep type-specific geometry based only
   on image observations.
3. Implement `identify()` with `identify_image()` so prompts receive neutral targets, own-box
   OCR, and permitted reference labels.
4. Implement `compare()` with `compare_observations()`, register the type in
   `PlanogramCompliance`, and provide a slots definition and bindings.

## Scoring and assessment

Every expected facing remains in its shelf denominator. `match` and `expected_empty` receive
strict/lenient `1.0/1.0`; `inferred_present` and `variant_unresolved` receive `0.0/1.0`;
`misplaced` receives `0.0/0.5`; all other statuses, including `unexpected_occupied`, receive
`0.0/0.0`.

Expected-empty facings distinguish `expected_empty` from `unexpected_occupied`. For product
shelves, coverage is resolved facings divided by expected facings. Zone-only units use assessed
mandatory rules divided by mandatory rules; their valid definition coverage is `1.0`. Thresholds
still apply when a unit has zero facings. Evidence quality reports source strength and never
changes credit. A complete result can be noncompliant; uncertainty is inconclusive and never
compliant.

## Informative rules

`fact_tag_present` binds to one facing and must set `mandatory` to `false`. It passes when a fact
or price tag is anchored to that facing's slot in any photo. Tags are perceived only by planogram
types with a tag shape profile: `product_on_shelves` and `endcap_backlit_multitier`; InkWall price
tags anchor slots.

Informative outcomes appear in `shelf_scores[].info_results` and
`compliance_results[].assessment.info_results`, never in `rule_results`. They do not change a
score, coverage, or status.

| Parameter | Meaning | Default |
|---|---|---|
| `mandatory` | Must be `false`; informative rules cannot be mandatory. | `false` |
| `price_required` | Requires an amount to be legible on the anchored tag; it does not compare against an expected price. | `false` |

## Result keys

`run()` always returns the eight established keys: `step3_compliance_results`,
`compliance_results`, `overall_compliance_score`, `overall_compliant`, `identified_products`,
`shelf_regions`, `rendered_image`, and `overlay_path`. Rendered-image fields refer to the first
successfully processed image, while `shelf_regions` are observed regions.

Additive keys are `detections`, `identifications`, `position_results`, `products_found`, `shelf_scores`, `coverage`,
`detected_products`, `definition_coverage`, `assessment_status`, `strict_compliance_score`,
`evidence_quality`, `detection_source`, `ocr_available`, `resolved_backend`, `renders`, and
`errors`. New runs report `cv`, `llm`, or `mixed` detection provenance; older serialized
historical values remain parseable.

For conversion and deployment, read the [migration runbook](planogram-cycle-migration.md). For
opt-in live validation, see the [live E2E harness](../../examples/planogram/e2e/README.md).
