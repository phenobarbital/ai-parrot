# TASK-4175: Apply CompletenessPolicy in summarize, project_compliance and compare_observations

**Feature**: FEAT-646 — Ink-wall slot recovery and completeness policy
**Spec**: `sdd/specs/ink-wall-registration-and-completeness.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4174
**Assigned-to**: unassigned

---

## Context

Spec §1 defect 2 and §2 Part B. Today `summarize()` marks the run `COMPLETE` only when every position is
resolved, and `project_compliance()` applies the same all-or-nothing rule per shelf, so one unresolved
facing out of 102 makes an ink-wall photo inconclusive. This task threads the `CompletenessPolicy`
(created by TASK-4174) into both functions as an optional keyword and forwards `ctx.layout.completeness`
from `compare_observations()`. With the default policy (1.0 / 1.0) both functions must behave exactly as
today (AC4); with a tolerant policy only `assessment_status` (and what depends on `complete`) may change,
never a score or credit (AC5, G4).

---

## Scope

- `summarize(..., *, completeness: Optional[CompletenessPolicy] = None)`: global `COMPLETE` iff shelf scores
  exist, `coverage >= policy.min_coverage`, every status-relevant rule outcome is assessed, and positions or
  rule results exist. `None` ⇒ `CompletenessPolicy()`.
- `project_compliance(..., *, policy=None, completeness: Optional[CompletenessPolicy] = None)`: a shelf is
  complete iff `(len(shelf.facings) - len(unresolved_ids)) / len(shelf.facings) >= min_shelf_coverage` and its
  rules are complete; a shelf with zero facings keeps the rule-only completeness.
- `compare_observations()` passes `completeness=getattr(ctx.layout, "completeness", None)` to both calls.
- Tests in `test_scoring_projection.py` (spec §4 M2 rows).

**NOT in scope**: the model / layout fields (TASK-4174); `finalize_comparison` (unchanged — still requires
`COMPLETE` and every shelf `COMPLIANT`); `CreditPolicy`, thresholds and score formulas (Non-Goals).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py` | MODIFY | `completeness` kw in `summarize` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py` | MODIFY | `completeness` kw in `project_compliance` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py` | MODIFY | forward `ctx.layout.completeness` |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py` | MODIFY | M2 tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_pipelines.planogram.comparison.definition import CompletenessPolicy  # created by TASK-4174 (definition.py, after ReportingPolicy)
# scoring.py:10-16 already imports from parrot_pipelines.planogram.comparison.definition (multi-line; add CompletenessPolicy)
# projection.py:11 — from parrot_pipelines.planogram.comparison.definition import FacingDefinition, ReportingPolicy, SlotsDefinition
from parrot_pipelines.planogram.comparison.scoring import summarize, score_shelves, merge_positions  # scoring.py:430
from parrot_pipelines.planogram.comparison.projection import project_compliance, finalize_comparison  # projection.py:56, :169
from parrot_pipelines.planogram.contracts import AssessmentStatus, FacingStatus
```

### Existing Signatures to Use
```python
# comparison/scoring.py:430
def summarize(shelf_scores, positions, definition, weights: EvidenceWeights) -> ComparisonResult
#   resolved = [p for p in positions if p.status in _RESOLVED]
#   coverage = len(resolved)/len(positions)  (zone-only run: assessed rule outcomes / rule outcomes)
#   rules_complete = all(o.assessed for o in rule_results)                         # :466
#   complete = (bool(shelf_scores) and len(resolved) == len(positions) and rules_complete
#               and (bool(positions) or bool(rule_results)))                       # :467-472

# comparison/projection.py:56
def project_compliance(shelf_scores, positions, definition, description, *,
                       policy: Optional[ReportingPolicy] = None) -> List[ComplianceResult]
#   unresolved_ids = [f.facing_id for f, status in zip(shelf.facings, statuses) if status not in _RESOLVED]
#   rules_complete = all(o.assessed for o in score.rule_results)
#   complete = not unresolved_ids and rules_complete                               # :110
#   `complete` also gates COMPLIANT / MISSING / MISPLACED (:134-139) and ShelfAssessment.assessment_status (:143)
def finalize_comparison(comparison, compliance_results) -> ComparisonResult       # :169 — unchanged

# stages/compare.py:188
def compare_observations(perceptions, identifications, ctx, description) -> ComparisonResult
#   comparison = summarize(shelves, positions, definition, ctx.evidence_weights)                      # :219
#   comparison, project_compliance(shelves, positions, definition, description, policy=policy)         # :228

# contracts.py
class CycleContext:  layout: Any = None  # :387 — may be None on non-cycle paths

# tests/planogram_cycle/test_scoring_projection.py helpers
def _run(definition, description, registrations, identifications, bindings=(), outcomes=None)  # :29
def _definition(shelves: Sequence[Tuple[str, str, int]], undescribed=None, zones=None)            # :41
def _description(levels, endcap=False)                                                           # :65
def _obs(image_id, shape_id, product, source="cv", uncertain=False, evidence=..., empty=False, brand=None)  # :78
def _observe(image_id, facings: Dict[str, Identification])                                       # :105
def _match_all(definition, image_id="img0", source="cv")                                          # :115
```

### Does NOT Exist
- ~~`summarize(..., min_coverage=...)`~~ — the keyword is `completeness`, a `CompletenessPolicy`
- ~~`ReportingPolicy.min_coverage`~~ — completeness does not live on `ReportingPolicy`
- ~~`ctx.completeness`~~ — read it from `ctx.layout` with `getattr(ctx.layout, "completeness", None)`
- ~~`FacingStatus.UNOBSERVED`~~ — not real, not added

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/scoring.py#summarize",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py#project_compliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py#finalize_comparison",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py#compare_observations"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Default ⇒ identical behaviour (AC4).** With 1.0, `coverage >= 1.0` ⇔ `len(resolved) == len(positions)`
  (both are exact integer ratios); for a zone-only run `coverage >= 1.0` ⇔ `rules_complete`. Keep the existing
  `rules_complete` and `(bool(positions) or bool(rule_results))` terms — do not drop them.
- **Scores never change (AC5, G4).** Only the boolean `complete` changes; credits, `coverage`,
  `overall_compliance_score`, `strict_compliance_score` and shelf scores are computed exactly as before.
- Per shelf, the denominator is `len(shelf.facings)` — the same domain `unresolved_ids` is computed over.
  Zero facings ⇒ `complete = rules_complete` (division guarded).
- Because shelf `complete` already gates COMPLIANT/MISSING/MISPLACED, a tolerant shelf can now be COMPLIANT
  while having unresolved facings (their 0 credit lowers `facing_lenient`). That is intended (spec §2 Part B).

---

## Implementation Blueprint

### Steps (in order)
1. Add `CompletenessPolicy` to the definition imports of `scoring.py` and `projection.py` — *why*: both signatures type the new keyword with it.
2. Add the keyword + docstring line to `summarize`, then rewrite the `complete = (...)` expression — *why*: spec §3 M2 skeleton.
3. Add the keyword + docstring line to `project_compliance`, then replace line 110 — *why*: per-shelf rule.
4. Forward the layout policy in `compare_observations` — *why*: that is how configs reach scoring.
5. Write the tests; run the Validation Commands (existing suites must stay green — AC4).

### `.../comparison/scoring.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^    FacingDefinition,$' comparison/scoring.py)
# BEFORE — insert above `    FacingDefinition,` (verified: comparison/scoring.py:11), first entry of the definition import block
    CompletenessPolicy,

# occurrences: 1 (verified: grep -c '    weights: EvidenceWeights,' comparison/scoring.py)
# AFTER — insert below `    weights: EvidenceWeights,` (verified: comparison/scoring.py:434)
    *,
    completeness: Optional[CompletenessPolicy] = None,

# occurrences: 1 (verified: grep -c 'weights: Evidence weights (evidence quality only' comparison/scoring.py)
# AFTER — insert below `        weights: Evidence weights (evidence quality only — never credits).` (verified: comparison/scoring.py:443)
        completeness: Minimum resolved fraction for ``COMPLETE`` (default: every position resolved). Never
            changes scores or credits.

# occurrences: 1 (verified: grep -c '    complete = (' comparison/scoring.py)
# REPLACE the `complete = (...)` expression at comparison/scoring.py:467-472
    policy = completeness or CompletenessPolicy()
    complete = (
        bool(shelf_scores)
        and coverage >= policy.min_coverage
        and rules_complete
        and (bool(positions) or bool(rule_results))
    )
```
**Why**: spec §2 Part B global rule. `coverage` is already computed above (both branches), so reuse it.

### `.../comparison/projection.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot_pipelines.planogram.comparison.definition import FacingDefinition, ReportingPolicy, SlotsDefinition' comparison/projection.py)
# REPLACE line 11
from parrot_pipelines.planogram.comparison.definition import (
    CompletenessPolicy,
    FacingDefinition,
    ReportingPolicy,
    SlotsDefinition,
)

# occurrences: 1 (verified: grep -c '    policy: Optional\[ReportingPolicy\] = None,' comparison/projection.py)
# AFTER — insert below `    policy: Optional[ReportingPolicy] = None,` (verified: comparison/projection.py:62)
    completeness: Optional[CompletenessPolicy] = None,

# occurrences: 1 (verified: grep -c 'policy: Optional reporting policy. The default preserves legacy display labels.' comparison/projection.py)
# AFTER — insert below that Args line (verified: comparison/projection.py:82)
        completeness: Minimum resolved fraction of a shelf's facings for a complete shelf (default: all).

# FILL IN: before the `for shelf in definition.shelves:` loop add `shelf_policy = completeness or CompletenessPolicy()`

# occurrences: 1 (verified: grep -c '        complete = not unresolved_ids and rules_complete' comparison/projection.py)
# REPLACE comparison/projection.py:110
        if shelf.facings:
            resolved_share = (len(shelf.facings) - len(unresolved_ids)) / len(shelf.facings)
            complete = resolved_share >= shelf_policy.min_shelf_coverage and rules_complete
        else:
            complete = rules_complete
```
**Why**: spec §3 M2 per-shelf rule; with 1.0 `resolved_share >= 1.0` ⇔ `not unresolved_ids`, so AC4 holds.

### `.../stages/compare.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    comparison = summarize(shelves, positions, definition, ctx.evidence_weights)' stages/compare.py)
# REPLACE stages/compare.py:219
    completeness = getattr(ctx.layout, "completeness", None)
    comparison = summarize(shelves, positions, definition, ctx.evidence_weights, completeness=completeness)

# occurrences: 1 (verified: grep -c 'comparison, project_compliance(shelves, positions, definition, description, policy=policy)' stages/compare.py)
# REPLACE stages/compare.py:228
        comparison,
        project_compliance(shelves, positions, definition, description, policy=policy, completeness=completeness),
```
**Why**: `ctx.layout` is `Any` and may be `None` (spec §7 gotcha) — `getattr` keeps the default path.

### `tests/planogram_cycle/test_scoring_projection.py` (MODIFY — append)
```python
from parrot_pipelines.planogram.comparison.definition import CompletenessPolicy  # FILL IN: merge into the existing definition import at :11


def _scored(definition, description, idents_by_facing, completeness=None):
    """merge -> score -> summarize/project with a completeness policy; returns (finalized, results)."""
    # FILL IN: mirror _run (:29) but pass completeness= to summarize and project_compliance; return both the
    #   finalized ComparisonResult and the project_compliance list — bounded by AC4/AC5


def test_summarize_default_completeness_unchanged():
    """One unresolved position + default policy ⇒ INCONCLUSIVE (regression)."""
    # FILL IN — bounded by AC4


def test_summarize_tolerant_completeness():
    """97/102 resolved with min_coverage=0.9 ⇒ COMPLETE; scores identical to the default-policy run."""
    # FILL IN: a 102-facing definition (e.g. 6 shelves 17/18/18/18/18/13), 5 facings left unobserved (NOT_VISIBLE);
    #   compare overall/strict/coverage and every shelf score between default and tolerant — bounded by AC5


def test_summarize_tolerant_rules_still_required():
    """Coverage above the threshold but an unassessed status-relevant rule ⇒ INCONCLUSIVE."""
    # FILL IN: reuse the RuleOutcome / bindings pattern of test_scoring_fixture_zone_only_shelf (:213) — bounded by spec §2 Part B


def test_project_shelf_completeness():
    """14/15 resolved, min_shelf_coverage=0.8 ⇒ 'complete'; 11/15 ⇒ 'inconclusive'."""
    # FILL IN: assert results[0].assessment.assessment_status — bounded by spec §4


def test_overall_compliant_requires_complete_and_all_compliant():
    """Tolerant COMPLETE + one NON_COMPLIANT shelf ⇒ overall_compliant False."""
    # FILL IN: one shelf fully matched, one with many EMPTY facings (resolved but below threshold) — bounded by AC5/AC7
```

### FILL IN checklist
- [ ] `projection.py` — `shelf_policy` defined once before the loop
- [ ] `_scored` helper + five tests — bounded by AC4/AC5 and spec §4 M2 rows

---

## Acceptance Criteria

- [ ] AC4: with `CompletenessPolicy()` (or `None`) every existing test in `test_scoring_projection.py`,
      `test_reporting_projection.py`, `test_shared_comparison.py`, `test_ink_wall.py` keeps its `assessment_status`
- [ ] AC5: tolerant vs default runs have identical scores/coverage/credits; only completeness-driven fields differ
- [ ] `compare_observations` forwards `ctx.layout.completeness`; `ctx.layout=None` still works
- [ ] `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_reporting_projection.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_shared_comparison.py -q`
- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_ink_wall.py -q`

---

## Test Specification

See the test stubs in the Implementation Blueprint (spec §4 M2 rows).

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug ink-wall-registration-and-completeness --feature-id FEAT-646`); TASK-4174 must be `done`.
2. Verify the Codebase Contract; set this task `in-progress` in the per-spec index.
3. Implement from the blueprint; run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot-pipelines/src:packages/ai-parrot/src`.
4. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4175 ink-wall-registration-and-completeness verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none


**Completion Note (sdd-worker)**: merged via coder_merge; touched-module tests pass (100 passed, 2 skipped).
