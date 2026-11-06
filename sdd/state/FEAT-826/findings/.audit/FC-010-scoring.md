---
id: FC-010
query_id: Q019
type: read
intent: "Scoring and thresholds — how zone results roll up to overall compliance."
executed_at: 2026-11-06T16:08:10Z
duration_ms: 1500
parent_id: null
depth: 0
---

# FC-010 — Zone shelves score presence/text/visual with default weights; illumination is a multiplier

## Summary

`score_shelves` emits one `ShelfScore` per definition shelf. For a shelf without facings the "product" term is `zone_score` (share of required zones whose `zone_present` passed); text and visual terms are the mean of their rule scores (`appearance` counts as visual); failed assessed `illumination` rules subtract `penalty` from a multiplier. Weights come from `ShelfConfig` matched by `shelf.level` or from the header endcap rule; without a config the defaults are visual 0.2, text 0.1, product `1 - visual`. `rule_results` lists mandatory bindings plus assessed illumination only — non-mandatory rules are not listed. For zone-only runs, `summarize` derives coverage from rule outcomes and marks the run INCONCLUSIVE unless every listed rule was assessed.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py`
  lines: 34-36
  symbol: `_DEFAULT_VISUAL_WEIGHT`
  excerpt: |
    _DEFAULT_VISUAL_WEIGHT = 0.2
    _DEFAULT_TEXT_WEIGHT = 0.1
    _HEADER_VISUAL_SHARE = 0.2  # header/endcap: visual weight = endcap.product_weight * 0.2 (today's rule)
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py`
  lines: 232-274
  symbol: `_weights`
  excerpt: |
    is_header = bool(
        endcap is not None
        and getattr(endcap, "enabled", False)
        and shelf.level is not None
        and getattr(endcap, "position", None) == shelf.level
    )
    ...
    wv = visual if visual is not None else _DEFAULT_VISUAL_WEIGHT
    wt = text if text is not None else _DEFAULT_TEXT_WEIGHT
    wp = product if product is not None else (1 - wv)
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py`
  lines: 311-434
  symbol: `score_shelves`
  excerpt: |
    texts = [outcomes[b.rule_id] for b in shelf_bindings if b.kind == "text_requirements"]
    visuals = [outcomes[b.rule_id] for b in shelf_bindings if b.kind in ("visual_features", "appearance")]
    illumination = [outcomes[b.rule_id] for b in shelf_bindings if b.kind == "illumination"]
    ...
    penalty = sum(o.penalty for o in illumination if o.assessed and o.passed is False) / max(1, count)
    multiplier = max(0.0, 1 - penalty)
    ...
    rule_results = [outcomes[b.rule_id] for b in shelf_bindings
                    if b.mandatory or (b.kind == "illumination" and outcomes[b.rule_id].assessed)]
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py`
  lines: 437-494
  symbol: `summarize`
  excerpt: |
    else:
        # Zone-only run: coverage and evidence come from rule outcomes (spec §2 Stage 3).
        coverage = sum(1 for o in rule_results if o.assessed) / len(rule_results) if rule_results else 0.0
    ...
    rules_complete = all(o.assessed for o in rule_results)
    ...
    assessment_status=AssessmentStatus.COMPLETE if complete else AssessmentStatus.INCONCLUSIVE,

## Notes

- Unowned zones become virtual shelves with `level=None` (FC-022), so for the rewritten EcoTank rows `_weights` never takes the header branch and no `ShelfConfig` matches: every zone uses the 0.8 / 0.1 / 0.2 defaults (normalised over the applying terms).
- One unassessed mandatory rule (e.g. `zone_present` "zone visibility unknown", `illumination` "unknown") makes the whole run INCONCLUSIVE, and `overall_compliant` then cannot be true (FC-022).
