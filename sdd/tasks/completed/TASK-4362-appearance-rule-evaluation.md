# TASK-4362: Evaluate `appearance` rules, score them, document them

**Feature**: FEAT-683 — Planogram appearance rule
**Spec**: `sdd/specs/planogram-appearance-rule.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4359, TASK-4361
**Assigned-to**: unassigned

---

## Context

Spec §3 Modules 4 and 5. Given the `appearance` observations collected per zone crop (TASK-4360),
decide each configured attribute by an area-weighted majority across the zone's matched fragments,
exactly the way `_rule_illumination` decides illumination, and fold the outcome into the zone's
visual score. Then document the rule for config authors.

This task does not import anything from TASK-4360: it builds `RuleObservation(kind="appearance")`
objects directly in its tests, so it runs concurrently with TASK-4360.

---

## Scope

- Add `_rule_appearance` to `comparison/rules.py` (semantics: spec §2 Overview item 4).
- Dispatch `binding.kind == "appearance"` in `evaluate_rules`.
- In `score_shelves`, count `appearance` outcomes in the visual term.
- Add an "Appearance rules" section to `docs/pipelines/planogram-compliance-cycle.md`.
- Write `tests/planogram_cycle/test_appearance_rule.py`.

**NOT in scope**: the evidence prompt (TASK-4360); binding validation (TASK-4361); any change to
`project_compliance` (a failed mandatory rule already blocks `COMPLIANT` through `rule_results`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py` | MODIFY | `_rule_appearance` + dispatch |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py` | MODIFY | visual term includes `appearance` |
| `docs/pipelines/planogram-compliance-cycle.md` | MODIFY | "Appearance rules" section |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_appearance_rule.py` | CREATE | evaluation + scoring tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# rules.py already imports (lines 1-31): Dict, List, Optional, Sequence, Tuple; RuleBinding, SlotsDefinition,
# ZoneDefinition; ObservationRef, ObservationSource, PerceptionResult, RuleObservation, RuleOutcome, Shape, ...
# add from contracts (TASK-4359):
from parrot_pipelines.planogram.contracts import APPEARANCE_UNDETERMINED
# tests:
from parrot_pipelines.planogram.comparison.rules import evaluate_rules
from parrot_pipelines.planogram.comparison.scoring import score_shelves   # scoring.py:311
```

### Existing Signatures to Use
```python
# comparison/rules.py
def _unassessed(binding: RuleBinding, detail: str) -> RuleOutcome:                         # line 104
def _ref(image_id: str, target_id: str, source: ObservationSource) -> ObservationRef:       # line 109
def _dedupe_refs(refs: Sequence[ObservationRef]) -> List[ObservationRef]:                   # line 114
def _zone_matches(target_id, perceptions, definition, selectors)
    -> List[Tuple[str, ZoneDefinition, Optional[Shape], str]]:   # (image_id, zone, shape, status)  line 176
def _rule_observations(observations, image_id, target_ids, kind) -> List[RuleObservation]:  # line 204 (assessed only)
def _majority_state(votes: Sequence[Tuple[str, ObservationRef, int]])
    -> List[Tuple[str, ObservationRef]]:          # winners by summed area; a tie keeps every vote   line 355
def _rule_illumination(binding, perceptions, observations, definition, selectors) -> RuleOutcome:  # line 370 — PATTERN
def _rule_text(...)                                                                         # line 420
def evaluate_rules(perceptions, identifications, registrations, ctx) -> Dict[str, RuleOutcome]:  # line 577
    #   dispatch chain; `elif binding.kind == "fact_tag_present":` at line 602

# contracts.py:206
class RuleOutcome(BaseModel):
    rule_id: str; assessed: bool = False; passed: Optional[bool] = None; score: float = 1.0
    penalty: float = 0.0; detail: Optional[str] = None; observations: List[ObservationRef] = []

# comparison/scoring.py
def _mean_scores(outcomes: Sequence[RuleOutcome]) -> float:   # line 304 — unassessed earn 0.0
def score_shelves(positions, definition, bindings, rule_outcomes, description, policy) -> List[ShelfScore]:  # line 311
    #   line 359: visuals = [outcomes[b.rule_id] for b in shelf_bindings if b.kind == "visual_features"]
```

### Does NOT Exist
- ~~`RuleOutcome.attributes`~~ — per-attribute results go in `detail` only.
- ~~a generic `_vote()` helper~~ — reuse `_majority_state`; do not write a second voting scheme.
- ~~changes needed in `projection.py`~~ — none.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py",
      "action": "MODIFY"
    },
    {
      "path": "docs/pipelines/planogram-compliance-cycle.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_appearance_rule.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#_rule_illumination",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#_majority_state",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#_zone_matches",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#evaluate_rules",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py#score_shelves"
  ]
}
```

---

## Implementation Notes

### Semantics (spec §2 Overview item 4 — do not deviate)
For each configured attribute (`params` key; scalar value == one-item list):
1. For every matched fragment (`status == "matched"` and a shape), read the `appearance` observations of
   that shape; a value in `APPEARANCE_UNDETERMINED` does not vote. Each vote is `(value, ref, area)`.
2. Per image, reduce with `_majority_state`. A tie returns more than one distinct value → conflict.
3. No vote in any image → attribute **unassessed**. Different winning values across images, or a tie →
   attribute **unassessed** (conflict).
4. Otherwise the attribute **matches** when its value is in the accepted list, else it **mismatches**.

Rule outcome: `assessed` when ≥ 1 attribute is assessed (else `_unassessed(binding, "appearance not observed")`);
`passed` = no mismatch; `score` = matched / configured attributes; `detail` joins
`"<attr>: <value> (expected <a|b>)"` for each mismatch and `"<attr>: not assessed"` for each unassessed one
(`None` when everything matched); `observations` = deduped refs of the votes.

---

## Implementation Blueprint

### Steps (in order)
1. Import `APPEARANCE_UNDETERMINED` into the contracts import of rules.py — *why*: undetermined values never vote.
2. Insert `_rule_appearance` right above `def _rule_text(` — *why*: next to `_rule_illumination`, whose pattern it copies.
3. Add the dispatch branch — *why*: without it the rule falls to "unknown rule kind".
4. Widen the visual filter in scoring.py — *why*: spec §2 item 5.
5. Write the docs section and the tests.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def _rule_text(' rules.py)
# BEFORE — insert above `def _rule_text(` (verified: rules.py:420), with two blank lines around it
def _rule_appearance(
    binding: RuleBinding,
    perceptions: Sequence[PerceptionResult],
    observations: Sequence[RuleObservation],
    definition: SlotsDefinition,
    selectors: Sequence[object],
) -> RuleOutcome:
    """Evaluate closed-vocabulary zone appearance collected by the identification stage.

    Each configured attribute is decided by an area-weighted majority per image; an undetermined value
    never votes, and a tie or a disagreement across images leaves that attribute unassessed.
    """
    expected: Dict[str, List[str]] = {
        attribute: [value] if isinstance(value, str) else list(value) for attribute, value in binding.params.items()
    }
    matched = _zone_matches(binding.target_id, perceptions, definition, selectors)
    votes: Dict[str, Dict[str, List[Tuple[str, ObservationRef, int]]]] = {attribute: {} for attribute in expected}
    refs: List[ObservationRef] = []
    for image_id, _zone, shape, status in matched:
        if status != "matched" or shape is None:
            continue
        area = (shape.box.x2 - shape.box.x1) * (shape.box.y2 - shape.box.y1)
        for observation in _rule_observations(observations, image_id, [shape.shape_id], "appearance"):
            if not isinstance(observation.value, dict):
                continue
            ref = _ref(image_id, observation.target_id, observation.source)
            # FILL IN: for each attribute in expected, read observation.value.get(attribute); skip it when missing
            #          or in APPEARANCE_UNDETERMINED; else append (value, ref, area) to votes[attribute][image_id]
            #          and remember ref in refs — bounded by Semantics step 1
    # FILL IN: per attribute -> _majority_state per image, conflict/tie -> unassessed, else match/mismatch;
    #          build passed/score/detail per Semantics; nothing assessed -> _unassessed(binding, "appearance not observed")
    raise NotImplementedError
```
```python
# occurrences: 1 (verified: grep -cF '            elif binding.kind == "fact_tag_present":' rules.py)
# BEFORE — insert above that line (verified: rules.py:602), same indentation
            elif binding.kind == "appearance":
                outcome = _rule_appearance(binding, perceptions, observations, definition, selectors)
```
**Why this shape**: the signature is fixed by spec §3 Module 4 and matches `_rule_illumination`, so the
dispatch call is identical. Remove the `raise NotImplementedError` once the FILL INs are done.

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        visuals = [outcomes[b.rule_id] for b in shelf_bindings if b.kind == "visual_features"]' scoring.py)
# REPLACE scoring.py:359
        visuals = [outcomes[b.rule_id] for b in shelf_bindings if b.kind in ("visual_features", "appearance")]
```

### `docs/pipelines/planogram-compliance-cycle.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '## Informative rules' planogram-compliance-cycle.md) -->
<!-- BEFORE — insert above `## Informative rules` (verified: planogram-compliance-cycle.md:158) -->
## Appearance rules

FILL IN: 15–30 lines covering — the four attributes and their closed vocabulary (link `contracts.py`);
the params shape with the JSON example from spec §2; that `unknown` / `not_visible` never fail and are
never valid expectations; area-weighted majority and the cross-image conflict rule; that the evidence
prompt never contains configured values; advice: accept lists for lighting shifts (`["white", "grey"]`)
and keep `finish` in a separate non-mandatory binding until measured on real photos (spec §7).
```

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_appearance_rule.py` (CREATE)
```python
"""FEAT-683: appearance rule evaluation and scoring."""

import pytest

from parrot_pipelines.planogram.comparison.definition import RuleBinding
# FILL IN: imports for PerceptionResult, Shape, ShapeKind, ObservationSource, RuleObservation, FixtureMembership,
#          DetectionBox, SlotsDefinition/load_slots_definition, ZoneSelector, and the function under test.
#          Build fixtures the way tests/planogram_cycle/test_fact_tag_rule.py does (read it first).


def _binding(**params):
    return RuleBinding(rule_id="appearance:zone-base-1", kind="appearance", target_id="zone-base-1", params=params)


def test_appearance_all_match_passes():
    ...  # FILL IN: every attribute matches -> passed True, score 1.0, detail None


def test_appearance_mismatch_fails_with_detail():
    ...  # FILL IN: border_color grey vs ["blue"] -> passed False; "border_color: grey (expected blue)" in detail


def test_appearance_unknown_is_unassessed_not_failed():
    ...  # FILL IN: finish unknown, others match -> passed True, score < 1, "finish: not assessed" in detail


def test_appearance_nothing_known_unassessed():
    ...  # FILL IN: every attribute undetermined -> assessed False


def test_appearance_majority_by_area():
    ...  # FILL IN: small fragment grey + large fragment white -> background_color matches ["white"]


def test_appearance_conflict_across_images():
    ...  # FILL IN: image A white, image B blue -> background_color not assessed


def test_scalar_param_is_one_item_list():
    ...  # FILL IN: params {"background_color": "white"} behaves like ["white"]


def test_appearance_counts_in_visual_term():
    ...  # FILL IN: score_shelves with a failed mandatory appearance outcome -> lower visual score and the
    #          outcome is in rule_results (so projection marks the zone non-compliant)
```

### FILL IN checklist
- [ ] `_rule_appearance` vote collection (Semantics step 1)
- [ ] `_rule_appearance` decision, score and detail (Semantics steps 2-4 + outcome)
- [ ] docs "Appearance rules" section
- [ ] the eight tests

---

## Acceptance Criteria

- [ ] `_rule_appearance` follows the Semantics exactly; undetermined never fails; conflicts are unassessed
- [ ] `evaluate_rules` dispatches `appearance`
- [ ] A failed mandatory `appearance` rule lowers the visual term and makes the zone non-compliant
- [ ] Docs section present
- [ ] Existing `test_fact_tag_rule.py` and `test_scoring_projection.py` still pass; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_appearance_rule.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_rule.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Work in the feature worktree; TASK-4359 and TASK-4361 must be `done`.
2. Read `_rule_illumination` (rules.py:370-418) and `tests/planogram_cycle/test_fact_tag_rule.py` before writing code.
3. Verify every anchor with `grep -cF`; set `in-progress`; implement; complete every `FILL IN`.
4. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-pipelines/src`.
5. Commit only the four listed files; close with `scripts/sdd/close_task.sh TASK-4362 planogram-appearance-rule verified`.

---

## Completion Note

Seat: gpt-5.6-terra · Backend: codex · Attempts: 1 · Duration: 338s

**Completed by**: sdd-worker (coder gpt-5.6-terra)
**Date**: 2026-10-15
**Notes**: task tests pass; planogram_cycle suite green except pre-existing missing-examples errors.

**Deviations from spec**: none
