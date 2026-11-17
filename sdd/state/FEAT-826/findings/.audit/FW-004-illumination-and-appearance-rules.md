---
id: FW-004
query_id: Q004
type: wiki_query
intent: "Find how illumination / appearance (backlit ON vs OFF) is evaluated."
executed_at: 2026-11-06T16:11:08Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-004 — Backlit ON/OFF is the `illumination` rule (neutral per-zone observation, area-weighted vote); `appearance` (FEAT-683) adds closed-vocabulary colour/finish checks

## Summary

`_rule_illumination` evaluates `illumination` observations collected during identification for the zone's
matched shapes: an area-weighted majority per image, "conflict" (unassessed) when images disagree, and a pass
when the state equals `binding.params["required"]` (default `on`). FEAT-683 (`planogram-appearance-rule`,
status approved, target ai-parrot-pipelines 1.3.0) added the `appearance` rule kind — background colour, border
colour, finish, base surface colour from a closed vocabulary — evaluated by `_rule_appearance` along the same
path; unknown values are unassessed, never failures. The spec was measured on
`epson_depot_ecotank_not_backlit_planogram_config` and explicitly leaves the row update as a follow-up data
change; `migration.py` never emits `appearance` bindings.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
  lines: 391-438
  symbol: `_rule_illumination`
  wiki: `sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#_rule_illumination` (symbols lookup)
  excerpt: |
    matched = _zone_matches(binding.target_id, perceptions, definition, selectors)
    ...
    if not states:
        return _unassessed(binding, "illumination target not observed")
    ...
    if {"on", "off"}.issubset(distinct):
        return RuleOutcome(..., assessed=False, passed=None, score=0.0, detail="conflict: illumination differs across images", ...)
    required = str(binding.params.get("required", "on")).strip().lower()
    state = states[0][0]
    if state == required:
        return RuleOutcome(rule_id=binding.rule_id, assessed=True, passed=True, score=1.0, observations=refs)

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
  lines: 441-501
  symbol: `_rule_appearance`
  wiki: `sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#_rule_appearance` (symbols lookup; body not read in this lane)
  excerpt: |
    Evaluate closed-vocabulary zone appearance collected by the identification stage.

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
  lines: 550-590
  symbol: `_rule_visual`
  wiki: `sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#_rule_visual` (symbols lookup; body not read in this lane)
  excerpt: |
    Evaluate visual features from neutral observations and text evidence.

- path: `sdd/specs/planogram-appearance-rule.spec.md`
  lines: 10-13, 29-33, 52-55, 91-92
  symbol: `FEAT-683`
  wiki: `file:sdd/specs/planogram-appearance-rule.spec.md` (Q004 score 1.00)
  excerpt: |
    **Feature ID**: FEAT-683 ... **Status**: approved
    Measured on `epson_depot_ecotank_not_backlit_planogram_config` (4 valid photos, 20 zone
    observations, 2026-10-15): expected features `white rectangular graphic`, `blue border`,
    `circular icons`, `blue floor base` scored a minimum of 0.25 against a 0.5 threshold, which failed
    one valid photo.
    - Converting legacy configs: `migration.py` never emits `appearance` bindings; they are authored by hand.
    - Updating any row of `troc.planograms_configurations`. Adding `appearance` bindings to
      `epson_depot_ecotank_not_backlit_planogram_config` is a follow-up data change once this ships.
    A mandatory failed `appearance` rule blocks `COMPLIANT` through the existing `rule_results` path

## Notes

- FEAT-683 spec, Problem Statement: `visual_features` (`_rule_visual`) "scores a configured phrase as found when
  **any one word** of it appears anywhere in those phrases, and the model rarely names colours" — relevant to the
  ticket check "Top Graphic is correct image": a keyword `visual_features` binding is a weak identity check.
- Configuration shape from the spec: `{"rule_id": "appearance:zone-base-1", "kind": "appearance", "target_id":
  "zone-base-1", "mandatory": true, "params": {"background_color": ["white"], "border_color": ["blue"], ...}}`
  inside `planogram_config.rule_bindings`.
- Other Q004 hits: `flowtask::file:sdd/specs/graphic-panel-display.spec.md` (1.00),
  `file:sdd/tasks/completed/TASK-4360-appearance-evidence.md` (0.78).
- [cross-lane: type=read, intent=read comparison/rules.py _rule_visual and identification/references.py to establish what can verify 'top graphic is the correct image' for a ZONE (reference images vs keyword visual_features)]
