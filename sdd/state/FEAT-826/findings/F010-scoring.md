---
id: F010
query_id: Q019, Q029
type: read
intent: "Scoring and thresholds — how zone results roll up to overall compliance."
executed_at: 2026-11-06T16:08:10Z
duration_ms: 1900
parent_id: null
depth: 0
lanes: [codebase, git]
merged_from: [FC-010, FG-001]
---
# F010 — Zone shelves score presence/text/visual with default weights; illumination is a multiplier

## Summary

**[F010 · codebase]** `score_shelves` emits one `ShelfScore` per definition shelf. For a shelf without facings the "product" term is `zone_score` (share of required zones whose `zone_present` passed); text and visual terms are the mean of their rule scores (`appearance` counts as visual); failed assessed `illumination` rules subtract `penalty` from a multiplier. Weights come from `ShelfConfig` matched by `shelf.level` or from the header endcap rule; without a config the defaults are visual 0.2, text 0.1, product `1 - visual`. `rule_results` lists mandatory bindings plus assessed illumination only — non-mandatory rules are not listed. For zone-only runs, `summarize` derives coverage from rule outcomes and marks the run INCONCLUSIVE unless every listed rule was assessed.

**[F010 · git]** `git log --since=2026-10-01 -- packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/` on local `dev` returns 53 commits (Jesus Lara, plus one PR merge by phenobarbital), clustered on
2026-10-01/02 (cycle refactor follow-ups: ROI before detection, native `box_2d`, zone selectors),
2026-10-08/09 (ink wall, FEAT-645/646), 2026-10-12 (products-found endcap) and 2026-10-15 (appearance rule
FEAT-683, out-of-vocabulary appearance fix, comparison-rules fixes, per-requirement text features).
**After 2026-10-15 only two commits touch the package**: `dda9a3ed2a` (2026-10-27, CI repair, 7 lines in
`comparison/scoring.py` + `perception/rows.py`) and `321c9883a3` (2026-11-05, docs move). No planogram code
commit exists between 2026-10-16 and 2026-10-26, i.e. nothing landed in the days around the ticket reopen (2026-10-21).

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
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/`
  commits (newest first, date · author · subject):
  - `321c9883a3` 2026-11-05 · Jesus · feat(github-wiki-technical-reference): TASK-5172 — move technical docs to wiki/
  - `dda9a3ed2a` 2026-10-27 · Jesus Lara · fix(ci): repair nightly setup and package regressions
  - `e168ddc9f2` 2026-10-15 · Jesus Lara · feat(comparison-rules-fixes-2): TASK-4368 — per-requirement text features
  - `af3b2e346f` 2026-10-15 · phenobarbital · Merge pull request #1681 from phenobarbital/feat-FEAT-685-comparison-rules-fixes
  - `d9e46ba0bf` 2026-10-15 · Jesus Lara · feat(comparison-rules-fixes): TASK-4365 — opt-in visual_features checklist
  - `dedc07b82f` 2026-10-15 · Jesus Lara · feat(comparison-rules-fixes): TASK-4366 — read superscript-cents prices on fact tags
  - `b1d8d506dc` 2026-10-15 · Jesus Lara · fix(planogram): coerce out-of-vocabulary appearance answers to unknown
  - `dd059bfa79` 2026-10-15 · Jesus Lara · feat(planogram-appearance-rule): TASK-4362 — engine-committed coder deliverable
  - `95354e6569` 2026-10-15 · Jesus Lara · feat(planogram-appearance-rule): TASK-4360 — engine-committed coder deliverable
  - `2c371cf2b2` 2026-10-15 · Jesus Lara · feat(planogram-appearance-rule): TASK-4361 — engine-committed coder deliverable
  - `1bbe2dfe30` 2026-10-15 · Jesus Lara · feat(planogram-appearance-rule): TASK-4359 — engine-committed coder deliverable
  - `fa07958931` 2026-10-12 · Jesus Lara · fix(planogram): TASK-4236 — ProductCounter/GraphicPanelDisplay resolve their own lay…
  - `7a6d231dee` 2026-10-12 · Jesus Lara · feat(products-found-endcap): TASK-4206 — engine-committed coder deliverable
  - `42a93f350f` 2026-10-09 · Jesus Lara · fix(planogram): skip reference images for types that do not use them
  - `63767aac9c` 2026-10-02 · Jesus Lara · feat(planogram): phrases read off a zone crop count as text evidence
  - `25d854f217` 2026-10-02 · Jesus Lara · feat(planogram): ROI components as observed zones (roi_zone_labels)
  - `7e245da242` 2026-10-02 · Jesus Lara · feat(planogram): fixture ROI before LLM detection; native box_2d answers
  - `59686f956e` 2026-10-02 · Jesus Lara · fix(planogram): cut back an oversized fixture ROI; agreeing reference is evidence
  - `d620279f1f` 2026-10-01 · Jesus Lara · feat(planogram): fixture-band zone selectors for fragmented zone detections
  - `bea8b4a8e9` 2026-10-01 · Jesus Lara · fix(planogram): drop reference_id without references; retry truncated answers
- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
  commit: `e168ddc9f2` 2026-10-15 — 31 lines changed, plus new test
  `packages/ai-parrot-pipelines/tests/planogram_cycle/test_text_requirements_case.py` (117 lines)

## Notes

*From F010:*
- Unowned zones become virtual shelves with `level=None` (F020), so for the rewritten EcoTank rows `_weights` never takes the header branch and no `ShelfConfig` matches: every zone uses the 0.8 / 0.1 / 0.2 defaults (normalised over the applying terms).
- One unassessed mandatory rule (e.g. `zone_present` "zone visibility unknown", `illumination` "unknown") makes the whole run INCONCLUSIVE, and `overall_compliant` then cannot be true (F020).

*From F010:*
- The log was taken on local `dev` (5 ahead / 1 behind `origin/dev` at session start); see F023 for the
  `origin/main` ancestry checks.
- The remaining ~30 commits of the 53 are ink-wall work (FEAT-645 / FEAT-646, 2026-10-08/09) and 2026-10-02
  product-shelf registration fixes — not relevant to a zone-only promotional endcap.
- `dda9a3ed2a` is the only post-2026-10-15 behaviour change and it is specific to promotional displays with
  optional zones — directly relevant to graphics-only endcaps such as rows 23/24.
- [cross-lane: type=read, intent=read score_shelves around lines 330-360 of comparison/scoring.py to confirm how a zone-only promotional shelf with optional zones is scored after dda9a3ed2a]
