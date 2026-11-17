---
id: F008
query_id: Q017, Q004, Q009
type: read
intent: "Rule kinds available to a zone: presence, text, visual, appearance, illumination."
executed_at: 2026-11-06T16:06:30Z
duration_ms: 2200
parent_id: null
depth: 1
lanes: [codebase, wiki]
merged_from: [FC-008, FW-004, FW-009]
---
# F008 — Six rule kinds; "correct image" has no image-similarity rule, only text + keyword visual features

## Summary

**[F008 · codebase]** `evaluate_rules` dispatches six kinds: `zone_present`, `illumination`, `text_requirements`, `visual_features` (optional counted `checklist`), `appearance`, `fact_tag_present`; anything else is "unknown rule kind" (unassessed). `zone_present` passes on a matched shape or a positive region observation and is *unassessed* (not failed) when visibility is unknown or the match is ambiguous. `illumination` compares an area-weighted majority state with `params.required` (default `on`) and, on mismatch, fails with `params.penalty` (default 0.5) and a "backlight X (required: Y)" detail. `visual_features` passes at keyword-overlap ≥ `threshold` (default 0.5) using a stop-word list and a small synonym table. No rule compares a zone against a reference image.

**[F008 · wiki]** `_rule_illumination` evaluates `illumination` observations collected during identification for the zone's
matched shapes: an area-weighted majority per image, "conflict" (unassessed) when images disagree, and a pass
when the state equals `binding.params["required"]` (default `on`). FEAT-683 (`planogram-appearance-rule`,
status approved, target ai-parrot-pipelines 1.3.0) added the `appearance` rule kind — background colour, border
colour, finish, base surface colour from a closed vocabulary — evaluated by `_rule_appearance` along the same
path; unknown values are unassessed, never failures. The spec was measured on
`epson_depot_ecotank_not_backlit_planogram_config` and explicitly leaves the row update as a follow-up data
change; `migration.py` never emits `appearance` bindings.

**[F008 · wiki]** `wikitoolkit ledger context` over `plan.py`, `migration.py` and `comparison/rules.py` returns a single open
issue: `issue:cc0725ca11e4` (tech_debt, low, discovered from `spec:FEAT-683`) — in `_rule_appearance` the
"ambiguous zone match" reason is lost when no attribute is assessed, and the scalar-or-list normalisation of
expected values is duplicated in `comparison/definition.py` `validate_bindings`. Nothing in the ledger concerns
the Office Depot EcoTank rows, the migration, or FlowTask.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
  lines: 738-754
  symbol: `evaluate_rules`
  excerpt: |
    if binding.kind == "zone_present":
        outcome = _rule_zone_present(binding, perceptions, observations, definition, selectors)
    elif binding.kind == "illumination":
    elif binding.kind == "text_requirements":
    elif binding.kind == "visual_features":
    elif binding.kind == "appearance":
    elif binding.kind == "fact_tag_present":
    else:
        outcome = _unassessed(binding, "unknown rule kind")
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
  lines: 325-373
  symbol: `_rule_zone_present`
  excerpt: |
    if present:
        return RuleOutcome(rule_id=binding.rule_id, assessed=True, passed=True, score=1.0, observations=present)
    if absent:
        return RuleOutcome(..., assessed=True, passed=False, score=0.0, detail="zone region inspected: absent", ...)
    if any(status == "ambiguous" ...):
        return _unassessed(binding, "ambiguous zone match")
    return _unassessed(binding, "zone visibility unknown")
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
  lines: 391-438
  symbol: `_rule_illumination`
  excerpt: |
    if not states:
        return _unassessed(binding, "illumination target not observed")
    ...
    required = str(binding.params.get("required", "on")).strip().lower()
    state = states[0][0]
    if state == required:
        return RuleOutcome(rule_id=binding.rule_id, assessed=True, passed=True, score=1.0, observations=refs)
    ...
        penalty=float(binding.params.get("penalty", 0.5)),
        detail=f"{name} — backlight {state.upper()} (required: {required.upper()})",
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
  lines: 72-122
  symbol: `visual_feature_match`
  excerpt: |
    def keywords(value: str) -> set[str]:
        return {word for word in value.lower().strip().split() if word not in stop_words and len(word) > 1}
    ...
    matched = sum(any(matches(word) for word in keywords(value)) for value in expected)
    return matched / len(expected)
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
  lines: 504-547
  symbol: `_rule_text`
  excerpt: |
    if not observed:
        return _unassessed(binding, "text target not observed")
    ...
    missing = [requirement.required_text for requirement, result in zip(requirements, results, strict=True)
               if requirement.mandatory and not result.found]
    return RuleOutcome(..., assessed=True, passed=not missing, ...,
        detail=f"missing mandatory text: {', '.join(missing)}" if missing else None,
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
  lines: 550-590
  symbol: `_rule_visual`
  excerpt: |
    if not observed:
        return _unassessed(binding, "visual target not identified")
    expected = [str(value) for value in binding.params.get("expected", [])]
    score = visual_feature_match(expected, detected)
    return RuleOutcome(..., passed=score >= float(binding.params.get("threshold", 0.5)), ...)
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
  lines: 441-501
  symbol: `_rule_appearance`
  wiki: `sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#_rule_appearance` (symbols lookup; body not read in this lane)
  excerpt: |
    Evaluate closed-vocabulary zone appearance collected by the identification stage.
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

*From F008:*
- Ticket mapping: "X graphic is present" = `zone_present`; "top graphic is correct image" can only be approximated by `text_requirements` + `visual_features` (+ `appearance`, `illumination`). In `visual_feature_match` a word matches when it is a substring of any detected keyword (`any(word in keyword ...)`), so the visual check is lenient.
- Backlit vs not-backlit is exactly one parameter: `illumination.params.required` = `on` (planogram 23) vs `off` (planogram 24).
- Only `illumination` failures carry a penalty; this matters for what the legacy projection reports (F020).

*From F008:*
- FEAT-683 spec, Problem Statement: `visual_features` (`_rule_visual`) "scores a configured phrase as found when
  **any one word** of it appears anywhere in those phrases, and the model rarely names colours" — relevant to the
  ticket check "Top Graphic is correct image": a keyword `visual_features` binding is a weak identity check.
- Configuration shape from the spec: `{"rule_id": "appearance:zone-base-1", "kind": "appearance", "target_id":
  "zone-base-1", "mandatory": true, "params": {"background_color": ["white"], "border_color": ["blue"], ...}}`
  inside `planogram_config.rule_bindings`.
- Other Q004 hits: `flowtask::file:sdd/specs/graphic-panel-display.spec.md` (1.00),
  `file:sdd/tasks/completed/TASK-4360-appearance-evidence.md` (0.78).
- [cross-lane: type=read, intent=read comparison/rules.py _rule_visual and identification/references.py to establish what can verify 'top graphic is the correct image' for a ZONE (reference images vs keyword visual_features)]

*From F008:*
- The issue body quotes `_rule_appearance` at "~L429-481"; the symbol outline now places it at L441-501, i.e. the
  file moved since the issue was opened.
- If a row for 23/24 uses a mandatory `appearance` binding, an ambiguous zone match will read as "appearance not
  observed" in the rule detail (item 1 of the issue) — cosmetic, but it obscures diagnosis.
