# TASK-4006: Route fact_tag_present outcomes to info_results

**Feature**: FEAT-624 — Planogram `fact_tag_present` rule
**Spec**: `sdd/specs/planogram-fact-tag-rule.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4003
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. The rule is informative only (spec §2, resolved by the product owner): its
outcomes must never reach `ShelfScore.rule_results`, which `summarize` (coverage,
`rules_complete`) and `project_compliance` (shelf status) read. They go to the new
`ShelfScore.info_results` and are projected to `ShelfAssessment.info_results`.

---

## Scope

- In `score_shelves`, split the shelf's bindings: `fact_tag_present` bindings feed only
  `info_results`; every other term (texts, visuals, illumination, zones, mandatory, coverage,
  `rule_results`) is computed from the remaining bindings exactly as today.
- In `project_compliance`, pass `info_results` to `ShelfAssessment`.
- Write the tests listed below.

**NOT in scope**: evaluating the rule (TASK-4005). Tests here inject `RuleOutcome`s directly.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py` | MODIFY | split bindings; fill `info_results` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py` | MODIFY | project `info_results` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_scoring.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.models.compliance import ShelfAssessment  # verified: packages/ai-parrot/src/parrot/models/compliance.py:38
from parrot_pipelines.models import PlanogramConfig  # verified: used by tests/planogram_cycle/test_scoring_projection.py:10
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition  # verified: comparison/definition.py:118,277
from parrot_pipelines.planogram.comparison.projection import finalize_comparison, project_compliance  # verified: test_scoring_projection.py:12
from parrot_pipelines.planogram.comparison.registration import ImageRegistration  # verified: comparison/registration.py:35
from parrot_pipelines.planogram.comparison.scoring import merge_positions, score_shelves, summarize  # verified: test_scoring_projection.py:14
from parrot_pipelines.planogram.contracts import (
    CreditPolicy, EvidenceWeights, Identification, ObservationSource, RuleOutcome,
)  # verified: test_scoring_projection.py:15-24
```

### Existing Signatures to Use
```python
# comparison/scoring.py
def score_shelves(positions, definition, bindings, rule_outcomes, description, policy) -> List[ShelfScore]:  # line 310
    # line 343: shelf_bindings = [b for b in bindings if target_shelf.get(b.target_id) == shelf.shelf_id]
    # lines 344-350: outcomes / texts / visuals / illumination built from shelf_bindings
    # line 391: mandatory = [outcomes[b.rule_id] for b in shelf_bindings if b.mandatory]
    # line 396: rule_results = [ ... for b in shelf_bindings if b.mandatory or (illumination and assessed) ]
    # line 414: rule_results=rule_results,   (inside ShelfScore(...))
def summarize(shelf_scores, positions, definition, weights) -> ComparisonResult:  # line 420 — reads ShelfScore.rule_results only

# comparison/projection.py
#   line 104-105: failed_rules / rules_complete read score.rule_results
#   line 126: assessment = ShelfAssessment(
#   line 134:     rule_results=[o.model_dump(mode="json") for o in score.rule_results],

# contracts.py:231 ShelfScore — info_results: List[RuleOutcome] added by TASK-4003
```

### Does NOT Exist
- ~~`ShelfScore.info_results`~~ before TASK-4003 lands — depend on it.
- ~~a weight or penalty for fact tags~~ — none; the formula is unchanged.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_scoring.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py#score_shelves",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py#summarize",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py#project_compliance"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The split happens once, at line 343, so every downstream term is automatically computed
  without the informative bindings — do not sprinkle `kind != "fact_tag_present"` filters.
- `info_results` keeps binding order and includes unassessed placeholders
  (`RuleOutcome(rule_id=..., detail="not evaluated")`) like `outcomes` does.
- In the feature worktree, `ShelfAssessment` comes from the MAIN checkout (see TASK-4003 notes):
  the projection assertion skips when `info_results` is not a `ShelfAssessment` field, and
  `project_compliance` must therefore pass `info_results` as a keyword that pydantic may ignore
  until merge — do not guard it with `hasattr`.

---

## Implementation Blueprint

### Steps (in order)
1. Split `shelf_bindings` at line 343 — *why*: one cut keeps every score/coverage/status term untouched.
2. Build `info_results` and pass it to `ShelfScore(...)` — *why*: the outcome must still reach the result.
3. Project it in `project_compliance` — *why*: API consumers read `ShelfAssessment`.
4. Write the tests.

### `comparison/scoring.py` (MODIFY — split)
```python
# occurrences: 1 (verified: grep -c '        shelf_bindings = \[b for b in bindings if target_shelf.get(b.target_id) == shelf.shelf_id\]' comparison/scoring.py)
# REPLACE line 343 (verified: comparison/scoring.py:343)
        scoped = [b for b in bindings if target_shelf.get(b.target_id) == shelf.shelf_id]
        # fact_tag_present is informative (FEAT-624): it never enters a score, coverage or status term.
        shelf_bindings = [b for b in scoped if b.kind != "fact_tag_present"]
        info_results = [
            rule_outcomes.get(b.rule_id) or RuleOutcome(rule_id=b.rule_id, detail="not evaluated")
            for b in scoped
            if b.kind == "fact_tag_present"
        ]
```

### `comparison/scoring.py` (MODIFY — ShelfScore)
```python
# occurrences: 1 (verified: grep -c '                rule_results=rule_results,' comparison/scoring.py)
# AFTER — insert below `                rule_results=rule_results,` (verified: comparison/scoring.py:414)
                info_results=info_results,
```
Also add one sentence to the `score_shelves` docstring: outcomes of `fact_tag_present` bindings
are carried in `info_results` and excluded from every score, coverage and status input.

### `comparison/projection.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            rule_results=\[o.model_dump(mode="json") for o in score.rule_results\],' comparison/projection.py)
# AFTER — insert below `            rule_results=[o.model_dump(mode="json") for o in score.rule_results],` (verified: comparison/projection.py:134)
            info_results=[o.model_dump(mode="json") for o in score.info_results],
```

### `tests/planogram_cycle/test_fact_tag_scoring.py` (CREATE)
```python
"""FEAT-624 — fact_tag_present outcomes are informative only."""

from __future__ import annotations

import pytest

from parrot.models.compliance import ShelfAssessment
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.comparison.projection import finalize_comparison, project_compliance
from parrot_pipelines.planogram.comparison.registration import ImageRegistration
from parrot_pipelines.planogram.comparison.scoring import merge_positions, score_shelves, summarize
from parrot_pipelines.planogram.contracts import (
    CreditPolicy,
    EvidenceWeights,
    Identification,
    ObservationSource,
    RuleOutcome,
)


def _setup():
    """One shelf, two facings, both matched in one image (copy of test_scoring_projection builders)."""
    definition = load_slots_definition(
        {
            "shelves": [
                {
                    "shelf_id": "s1",
                    "shelf_number": 1,
                    "level": "top",
                    "facings": [
                        {"facing_id": f"s1_f{i}", "shelf_id": "s1", "slot": i, "product": f"P{i}",
                         "brand": "Acme", "descriptors": {"display_name": f"Product {i}"}}
                        for i in (1, 2)
                    ],
                }
            ]
        }
    )
    description = PlanogramConfig(
        planogram_config={"brand": "Acme", "category": "T", "aisle": {"name": "T"},
                          "shelves": [{"level": "top", "height_ratio": 0.3, "products": []}]}
    ).get_planogram_description()
    idents = [
        Identification(shape_id=f"img0:s1_f{i}", image_id="img0", product=f"P{i}", occupancy="occupied",
                       evidence=["sku"], source=ObservationSource.CV, raw_confidence=0.9)
        for i in (1, 2)
    ]
    registration = ImageRegistration(image_id="img0", row_to_shelf={0: "s1"},
                                     assignments={f"img0:s1_f{i}": f"s1_f{i}" for i in (1, 2)})
    return definition, description, [registration], idents


def _run(bindings, outcomes):
    definition, description, registrations, idents = _setup()
    policy = CreditPolicy.default()
    positions = merge_positions(definition, registrations, idents, policy)
    shelves = score_shelves(positions, definition, bindings, outcomes, description, policy)
    comparison = summarize(shelves, positions, definition, EvidenceWeights())
    results = project_compliance(shelves, positions, definition, description)
    final = finalize_comparison(comparison.model_copy(update={"position_results": positions, "shelf_scores": shelves}), results)
    return shelves, final


FAILED = RuleOutcome(rule_id="fact_tag_present:s1_f1", assessed=True, passed=False, score=0.0, detail="fact tag not observed")
BINDING = RuleBinding(rule_id="fact_tag_present:s1_f1", kind="fact_tag_present", target_id="s1_f1", mandatory=False)


def test_failed_fact_tag_changes_no_score_or_status():
    base_shelves, base = _run([], {})
    shelves, final = _run([BINDING], {BINDING.rule_id: FAILED})
    for field in ("strict_score", "lenient_score", "coverage"):
        assert getattr(shelves[0], field) == getattr(base_shelves[0], field)
    # FILL IN: also assert equality of overall_compliance_score, coverage, overall_compliant and every
    #          compliance_results[i].compliance_status between `base` and `final` — bounded by spec §5 AC 4


def test_fact_tag_outcome_is_in_info_results_only():
    shelves, _ = _run([BINDING], {BINDING.rule_id: FAILED})
    assert [o.rule_id for o in shelves[0].info_results] == [BINDING.rule_id]
    assert all(o.rule_id != BINDING.rule_id for o in shelves[0].rule_results)


def test_missing_outcome_is_a_not_evaluated_placeholder():
    shelves, _ = _run([BINDING], {})
    assert shelves[0].info_results[0].detail == "not evaluated"


@pytest.mark.skipif(
    "info_results" not in ShelfAssessment.model_fields,
    reason="core ai-parrot resolves to the main checkout inside a worktree; runs after merge",
)
def test_projection_carries_info_results():
    _, final = _run([BINDING], {BINDING.rule_id: FAILED})
    assessment = final.compliance_results[0].assessment  # ComplianceResult.assessment: compliance.py:67
    assert assessment.info_results[0]["rule_id"] == BINDING.rule_id
```

### FILL IN checklist
- [ ] `test_failed_fact_tag_changes_no_score_or_status` — overall and per-result assertions; bounded by spec §5 AC 4.

---

## Acceptance Criteria

- [ ] A failing `fact_tag_present` outcome changes none of: shelf `strict_score`, `lenient_score`,
      `coverage`, compliance status, overall score, overall coverage, `overall_compliant`.
- [ ] The outcome is in `ShelfScore.info_results` and never in `rule_results`.
- [ ] `ShelfAssessment.info_results` is populated (asserted once the core field is importable).
- [ ] Existing scoring tests pass unchanged; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_scoring.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py -q`

---

## Test Specification

See the CREATE block: score/status invariance, routing, placeholder, projection.

---

## Agent Instructions

1. Work in the feature worktree; run tests with `PYTHONPATH=packages/ai-parrot-pipelines/src`.
2. Confirm TASK-4003 is `done`; verify the Codebase Contract; mark `in-progress`; implement; validate.
3. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4006 planogram-fact-tag-rule verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
