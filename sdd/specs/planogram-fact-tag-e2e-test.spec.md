---
type: feature
base_branch: dev
feature_id: FEAT-674
projects: [ai-parrot-pipelines]
tags: [planogram, fact-tag, testing]
---

# Feature Specification: Planogram fact-tag end-to-end test

**Feature ID**: FEAT-674
**Date**: 2026-10-15
**Author**: Claude (sdd-fix lane)
**Status**: approved
**Target version**: next

Resolves ledger issue:f7ac629eded3 (discovered from spec:FEAT-624,
`sdd/specs/planogram-fact-tag-rule.spec.md`).

---

## 1. Motivation & Business Requirements

### Problem Statement
FEAT-624 (`fact_tag_present`, informative rule) specified in its §4 an integration test,
`test_compare_observations_reports_fact_tags`: `compare_observations` over a two-shelf fixture
must return the `fact_tag_present` outcomes in `info_results` and an unchanged compliance result.
It was never written. Only unit pieces exist (`test_fact_tag_rule.py`, `test_fact_tag_scoring.py`);
nothing exercises `register_image -> evaluate_rules -> score_shelves -> project_compliance`
together. The `FixtureMembership.UNCERTAIN` path of `_rule_fact_tag` (spec FEAT-624 §2: "a tag is
any on-fixture **or uncertain-membership** shape") is also untested.

### Goals
- Add `test_compare_observations_reports_fact_tags` to
  `packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_scoring.py`.
- Cover the UNCERTAIN-membership tag path (counted, unlike OFF_FIXTURE).
- If the end-to-end test exposes a bug in `comparison/rules.py`, fix it within scope.

### Non-Goals
- No behaviour change to scoring, projection or the rule outcome table.
- No new fixtures shared across test modules.

---

## 2. Architectural Design

### Overview
Test-only. A two-shelf, four-facing `SlotsDefinition`; one `PerceptionResult` with PRODUCT shapes,
anchored slots in two rows, and FACT_TAG shapes below chosen slots (one with OCR `"$129.99"`, one
UNCERTAIN membership, one OFF_FIXTURE); one `IdentificationResult` reading every slot correctly.
`compare_observations` runs once without bindings and once with `fact_tag_present` bindings; the
two compliance results must be identical, and each shelf's `info_results` carries the expected
outcomes while `rule_results` carries none of them.

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `stages.compare.compare_observations` | exercised | full deterministic compare stage |
| `comparison.rules._rule_fact_tag` | exercised | UNCERTAIN / OFF_FIXTURE membership |

---

## 3. Module Breakdown

### Module 1: fact-tag end-to-end test
- **Path**: `packages/ai-parrot-pipelines/tests/planogram_cycle/test_fact_tag_scoring.py`
- **Responsibility**: integration test + UNCERTAIN-membership test.
- **Depends on**: existing code only.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_uncertain_membership_tag_counts` | M1 | an UNCERTAIN tag under the facing's slot passes; OFF_FIXTURE does not |

### Integration Tests
| Test | Description |
|---|---|
| `test_compare_observations_reports_fact_tags` | `compare_observations` over a two-shelf fixture returns the informative outcomes and an unchanged compliance result |

---

## 5. Acceptance Criteria
- [ ] `test_compare_observations_reports_fact_tags` passes and asserts: identical
      `overall_compliance_score`, `overall_compliant`, `coverage`, per-shelf statuses and
      strict/lenient scores with and without the bindings; `info_results` per shelf hold exactly the
      bound `fact_tag_present` outcomes with the expected pass/fail/detail; `rule_results` hold none.
- [ ] The UNCERTAIN-membership path is covered.
- [ ] `ruff check` clean on the touched file.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot_pipelines.planogram.stages.compare import compare_observations  # stages/compare.py:188
from parrot_pipelines.planogram.comparison.rules import _rule_fact_tag, evaluate_rules  # rules.py:504, :577
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition  # :162, :362
from parrot_pipelines.planogram.contracts import CycleContext, FixtureMembership  # contracts.py:374, :35
```

### Existing Class Signatures
```python
def compare_observations(perceptions, identifications, ctx: CycleContext, description) -> ComparisonResult
def _rule_fact_tag(binding, perceptions, identifications, registrations) -> RuleOutcome
```

### Does NOT Exist (Anti-Hallucination)
- No shared conftest fixture `tagged_shelf` — build the fixture inside the test module.

---

## 7. Open Questions
None.
