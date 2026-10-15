# TASK-4348: Fact-tag end-to-end compare test

**Feature**: FEAT-674 — Planogram fact-tag end-to-end test
**Spec**: `sdd/specs/planogram-fact-tag-e2e-test.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context
Resolves ledger issue:f7ac629eded3. FEAT-624's spec §4 required
`test_compare_observations_reports_fact_tags`; it was never written, and the UNCERTAIN
fixture-membership path of `_rule_fact_tag` is untested.

## Scope
- Add `test_compare_observations_reports_fact_tags` (two shelves, two facings each, real
  `compare_observations`, with vs. without `fact_tag_present` bindings).
- Add `test_uncertain_membership_tag_counts`.

**NOT in scope**: any change to scoring/projection; a fix in `rules.py` only if the test exposes a bug.

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_scoring.py` | MODIFY | add the two tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_pipelines.planogram.stages.compare import compare_observations  # stages/compare.py:188
from parrot_pipelines.planogram.comparison.rules import _rule_fact_tag  # rules.py:504
from parrot_pipelines.planogram.contracts import CycleContext, FixtureMembership, OcrReading, PerceptionResult, Shape, ShapeKind, Slot, IdentificationResult
```

### Existing Signatures to Use
```python
# stages/compare.py:188
def compare_observations(perceptions, identifications, ctx: CycleContext, description) -> ComparisonResult
# comparison/rules.py:504
def _rule_fact_tag(binding, perceptions, identifications, registrations) -> RuleOutcome
```

### Does NOT Exist
- No shared `tagged_shelf` conftest fixture.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_scoring.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/stages/compare.py#compare_observations",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py#_rule_fact_tag"
  ]
}
```

## Implementation Notes
Slots anchored to ON_FIXTURE PRODUCT shapes so `registrable_slots` keeps them; identifications keyed
by slot id so `register_image` assigns them. Tags sit just below a slot's box so `slot_above`
anchors them.

## Acceptance Criteria
- [ ] Both tests pass.
- [ ] `ruff check` clean on the test file.

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_scoring.py -q`

## Test Specification
See spec §4.

## Agent Instructions
Work in the feature worktree; touch only the listed file (and `rules.py` only for a bug the test exposes).

## Completion Note
*(Agent fills this in when done)*
