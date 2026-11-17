---
id: F013
query_id: Q023
type: grep
intent: "Illumination / backlit / appearance handling across the cycle."
executed_at: 2026-11-06T16:10:05Z
duration_ms: 400
parent_id: null
depth: 0
lanes: [codebase]
merged_from: [FC-015]
---
# F013 — Illumination is a first-class observation (on/off/unknown) asked per zone by the evidence stage

## Summary

`illumination|backlit|appearance` matches 16 files under `planogram/`; the heaviest are `identification/evidence.py` (24), `contracts.py` (22), `migration.py` (17), `comparison/rules.py` (16), `comparison/definition.py` (14). The evidence stage asks the vision model for illumination only when a zone has an `illumination` binding, stores `on | off | unknown`, and marks `unknown` as not assessed. This replaces the legacy prompt trick seen in the ticket logs (labelling the header `Epson_Top_Backlit_ON` vs `ERROR_LIGHT_IS_OFF`).

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py`
  lines: 43-43
  symbol: `(zone answer model)`
  excerpt: |
    illumination: Literal["on", "off", "unknown"] = "unknown"
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py`
  lines: 75-77
  symbol: `build_zone_prompt`
  excerpt: |
    if ask_illumination:
            "For illumination, report on for uniform self-emitted glow, frame halo, or luminous translucent "
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py`
  lines: 174-188
  symbol: `(zone evidence collection)`
  excerpt: |
    ask_illumination = "illumination" in kinds
    ...
    if not (ask_illumination or ask_features or ask_appearance or presence_zone_ids):
    ...
        prompt = build_zone_prompt(ask_illumination, ask_features, ask_appearance, checklist=checklist)
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/identification/evidence.py`
  lines: 208-215
  symbol: `(zone evidence collection)`
  excerpt: |
    if ask_illumination:
        ...
            kind="illumination",
            value=answer.illumination,
            assessed=answer.illumination != "unknown",

## Notes

- An `unknown` illumination answer leaves the mandatory rule unassessed → the run is INCONCLUSIVE and cannot be compliant (F010, F020). `packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py` has `test_unknown_illumination_is_inconclusive` (line 216) and `test_illumination_off_fails_mandatory_rule` (line 194).
- Only matching lines were read in `evidence.py`; the function name for lines 174-215 was not captured.
