---
id: FC-008
query_id: Q017
type: read
intent: "Rule kinds available to a zone: presence, text, visual, appearance, illumination."
executed_at: 2026-11-06T16:06:30Z
duration_ms: 2200
parent_id: null
depth: 0
---

# FC-008 — Six rule kinds; "correct image" has no image-similarity rule, only text + keyword visual features

## Summary

`evaluate_rules` dispatches six kinds: `zone_present`, `illumination`, `text_requirements`, `visual_features` (optional counted `checklist`), `appearance`, `fact_tag_present`; anything else is "unknown rule kind" (unassessed). `zone_present` passes on a matched shape or a positive region observation and is *unassessed* (not failed) when visibility is unknown or the match is ambiguous. `illumination` compares an area-weighted majority state with `params.required` (default `on`) and, on mismatch, fails with `params.penalty` (default 0.5) and a "backlight X (required: Y)" detail. `visual_features` passes at keyword-overlap ≥ `threshold` (default 0.5) using a stop-word list and a small synonym table. No rule compares a zone against a reference image.

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
  lines: 441-451
  symbol: `_rule_appearance`
  excerpt: |
    """Evaluate closed-vocabulary zone appearance collected by the identification stage.
    Each configured attribute is decided by an area-weighted majority per image; an undetermined value
    never votes, and a tie or a disagreement across images leaves that attribute unassessed.

## Notes

- Ticket mapping: "X graphic is present" = `zone_present`; "top graphic is correct image" can only be approximated by `text_requirements` + `visual_features` (+ `appearance`, `illumination`). In `visual_feature_match` a word matches when it is a substring of any detected keyword (`any(word in keyword ...)`), so the visual check is lenient.
- Backlit vs not-backlit is exactly one parameter: `illumination.params.required` = `on` (planogram 23) vs `off` (planogram 24).
- Only `illumination` failures carry a penalty; this matters for what the legacy projection reports (FC-022).
