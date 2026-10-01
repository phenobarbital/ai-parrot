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

## Result keys

`run()` always returns the eight established keys: `step3_compliance_results`,
`compliance_results`, `overall_compliance_score`, `overall_compliant`, `identified_products`,
`shelf_regions`, `rendered_image`, and `overlay_path`. Rendered-image fields refer to the first
successfully processed image, while `shelf_regions` are observed regions.

Additive keys are `detections`, `identifications`, `position_results`, `shelf_scores`, `coverage`,
`detected_products`, `definition_coverage`, `assessment_status`, `strict_compliance_score`,
`evidence_quality`, `detection_source`, `ocr_available`, `resolved_backend`, `renders`, and
`errors`. New runs report `cv`, `llm`, or `mixed` detection provenance; older serialized
historical values remain parseable.

For conversion and deployment, read the [migration runbook](planogram-cycle-migration.md). For
opt-in live validation, see the [live E2E harness](../../examples/planogram/e2e/README.md).
