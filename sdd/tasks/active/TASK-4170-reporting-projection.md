# TASK-4170: Project expected model labels without changing compliance scores

**Feature**: FEAT-645 — Planogram Ink Wall — model-based labels and slot presence
**Spec**: `sdd/specs/planogram-ink-wall-slot-presence.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4169
**Assigned-to**: unassigned

## Context

Implement spec §3 M5. Legacy reporting stays identical; product mode uses expected models and the shared presence truth table.

## Scope

- Add the keyword-only policy argument to project_compliance.
- Branch only expected/found/missing labels; retain unexpected identities and illumination details.
- Prove status, score, assessment and final overall_compliant invariance.

**NOT in scope**: scoring/credit/status changes, vision identification improvements, database writes,
flowtask persistence, dependencies, or files outside the table below.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py` | MODIFY | Optional reporting policy for labels |
| `packages/ai-parrot-pipelines/tests/planogram_cycle/test_reporting_projection.py` | CREATE | Policy parity and invariance tests |

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` during decomposition, 2026-10-08. Recheck anchors after dependencies land.
Existing imports below are verified in their source modules or installed dependencies.
Imports explicitly tagged with a task ID are planned dependency interfaces, not existing symbols at planning time.
Retain unrelated existing imports in MODIFY targets.

### Verified Imports

```python
from typing import List, Optional, Sequence
import pytest
from parrot.models.detections import AisleConfig, PlanogramDescription
from parrot.models.compliance import ComplianceResult
from parrot_pipelines.planogram.comparison.definition import FacingDefinition, ReportingPolicy, SlotsDefinition  # ReportingPolicy: TASK-4167
from parrot_pipelines.planogram.comparison.presence import facing_presence  # TASK-4169
from parrot_pipelines.planogram.comparison.projection import project_compliance, finalize_comparison
from parrot_pipelines.planogram.contracts import ComparisonResult, FacingStatus, PositionResult, ShelfScore, ObservationRef, RuleOutcome, AssessmentStatus
```

### Existing Signatures to Use

- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py:55` — `project_compliance`: (shelf_scores, positions, definition, description) -> List[ComplianceResult]; label assignments at 108/110/140
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py:42` — `_label`: display_name or product or facing_id fallback; preserve for default policy
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py:152` — `finalize_comparison`: (comparison: ComparisonResult, compliance_results: Sequence[ComplianceResult]) -> ComparisonResult; unchanged
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:231` — `ShelfScore`: rule_results, info_results, coverage and facing credit used by projection
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:206` — `RuleOutcome`: penalty/detail fields feed illumination pseudo-entries
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:218` — `PositionResult`: identity may contain a brand; never use it for product-mode found labels
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:195` — `ObservationRef`: raw_confidence supplies deciding threshold
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:325` — `ComparisonResult`: assessment_status plus existing score fields must remain invariant
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:170` — `FacingStatus`: status vocabulary unchanged
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py:187` — `AssessmentStatus`: COMPLETE/INCONCLUSIVE/LEGACY_UNMEASURED
- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:131` — `SlotsDefinition`: definition shelves provide occupied-expected facings

- `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py:78` — `FacingDefinition`: Existing projection import retained; occupied facings require a nonblank product.
- `packages/ai-parrot/src/parrot/models/detections.py:356` — `AisleConfig`: name: str; construct the required aisle fixture.
- `packages/ai-parrot/src/parrot/models/detections.py:364` — `PlanogramDescription`: Required brand, category, aisle and shelves fields; shelves=[] is valid.
- `packages/ai-parrot/src/parrot/models/compliance.py:52` — `ComplianceResult`: Expected/found/missing/unexpected are List[str]; status, score and assessment unchanged.

### Does NOT Exist

- No ComplianceResult.found_models or expected_models fields exist or are added.
- No policy parameter exists on project_compliance before this task.
- No reporting confidence gate belongs in scoring.py or finalize_comparison.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-pipelines/tests/planogram_cycle/test_reporting_projection.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py#project_compliance",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py#_label",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py#finalize_comparison",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#ShelfScore",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#RuleOutcome",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#PositionResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#ObservationRef",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#ComparisonResult",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#FacingStatus",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/contracts.py#AssessmentStatus",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#SlotsDefinition",
    "sym:packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/definition.py#FacingDefinition",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#AisleConfig",
    "sym:packages/ai-parrot/src/parrot/models/detections.py#PlanogramDescription",
    "sym:packages/ai-parrot/src/parrot/models/compliance.py#ComplianceResult"
  ]
}
```

## Implementation Notes

Keep _FOUND, _RESOLVED, _threshold, finalize_comparison and ComplianceResult models unchanged. AisleConfig/PlanogramDescription construction follows existing test_scoring_projection.py:65-75; verify those models before adding any other fixture field.

**Parallelism**: Consumes facing_presence from TASK-4169 (comparison/presence.py) and ReportingPolicy from its TASK-4167 ancestor; writes projection.py and its own tests. All mutations stay within declared files; `parallel: true`.
Do not change shared conftest files, rebuild extensions, or alter the environment.
Use the already-installed Pydantic v2 and pytest dependencies. No new dependency is needed.
Use strict type hints, Google-style docstrings, black (120 columns), and ruff on touched files.
Pure comparison helpers remain synchronous and perform no I/O.
Blueprint gaps are planning scaffolds only: completed implementation must contain no placeholders.

## Implementation Blueprint

### Steps (in order)
1. Extend the public signature with a keyword-only optional policy — because existing four-argument callers must remain valid.
2. Branch only labels and reuse facing_presence — because the feature must not change status decisions.
3. Compare serialized non-label fields and finalization — because equal numeric scores alone do not prove compliance invariance.

---

### `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py` (MODIFY)

```python
# MODIFY — add ReportingPolicy and presence import `from parrot_pipelines.planogram.comparison.definition import FacingDefinition, SlotsDefinition`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py:11)
# MODIFY — extend existing signature and label assignments `def project_compliance(`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py:55)
# MODIFY — choose product versus existing label `        missing = [_label(f) for f, status in occupied_expected if status == FacingStatus.EMPTY]`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py:108)
# MODIFY — branch on policy `        found = [(p.identity or _label(f)) for f, p in pairs if p is not None and p.status in _FOUND]`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py:110)
# MODIFY — use policy-selected expected labels `                expected_products=[_label(f) for f, _ in occupied_expected],`
# occurrences: 1 (verified: rg -n -F; packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/projection.py:140)
# Replace the definition import and add the presence import:
from parrot_pipelines.planogram.comparison.definition import FacingDefinition, ReportingPolicy, SlotsDefinition
from parrot_pipelines.planogram.comparison.presence import facing_presence


def project_compliance(
    shelf_scores: Sequence[ShelfScore],
    positions: Sequence[PositionResult],
    definition: SlotsDefinition,
    description: PlanogramDescription,
    *,
    policy: Optional[ReportingPolicy] = None,
) -> List[ComplianceResult]:
    """Project compliance with legacy labels by default and expected models on opt-in."""
    # Preserve existing projection body and docstring detail; add policy to Args.
    # FILL IN: branch only expected/missing/found labels (AC-1/2).
    # None or display_name -> exact current _FOUND and identity-or-_label behavior.
    # product -> expected model per occupied facing; found iff facing_presence(...)[0] is True.
    # Preserve illumination pseudo-entries and unexpected identities.
    # Do not replace this whole function with this scaffold or alter scoring/status logic.
    pass
```

**Why**: Only the reporting lists change. Reusing facing_presence prevents threshold and tri-state drift between representations.

### `packages/ai-parrot-pipelines/tests/planogram_cycle/test_reporting_projection.py` (CREATE)

```python
"""Reporting label policy and compliance invariance for FEAT-645."""
import pytest
from parrot.models.detections import AisleConfig, PlanogramDescription
from parrot_pipelines.planogram.comparison.definition import ReportingPolicy, SlotsDefinition
from parrot_pipelines.planogram.comparison.projection import finalize_comparison, project_compliance
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus, ComparisonResult, FacingStatus, ObservationRef, PositionResult, RuleOutcome, ShelfScore,
)


def test_project_compliance_product_labels() -> None:
    """Product mode lists expected models, preserves facings and excludes brand-only identity."""
    # FILL IN: brand identity, inferred/variant, mismatch, low/high misplaced and empty (AC-2).
    pass


def test_project_compliance_default_unchanged() -> None:
    """Omitted and display_name policies produce identical legacy serialized results."""
    # FILL IN: capture explicit legacy label expectations including MISMATCH (AC-1).
    pass


def test_scores_identical_across_policies() -> None:
    """Only label lists differ; projection and finalization decisions remain equal."""
    # FILL IN: compare status/score/assessment and finalize_comparison for both policies (AC-3).
    pass


def test_illumination_and_unexpected_labels_unchanged() -> None:
    """Illumination details and observed unexpected products keep their established meaning."""
    # FILL IN: rule penalty pseudo-entry and expected-empty unexpected identity (AC-2/3).
    pass
```

**Why**: Direct projection tests isolate reporting changes from upstream perception and retain explicit legacy assertions.

---

### FILL IN checklist

- [ ] Implement legacy/product label selection (AC-1/2).
- [ ] Fill label cardinality and full non-label invariance tests (AC-3).

---

## Acceptance Criteria

- [ ] AC-1: Four positional arguments remain supported; None and product_label=display_name preserve current labels and _FOUND membership, including MISMATCH.
- [ ] AC-2: Product mode uses expected product per occupied facing for expected, true-presence found and EMPTY missing; never brand identity in found; duplicate facings stay duplicated. Unexpected observed identities and illumination pseudo-entries are unchanged.
- [ ] AC-3: compliance_status, compliance_score, complete assessment, comparison scores and overall_compliant are identical across policies; existing test_scoring_projection.py assertions pass unchanged.

## Validation Commands

- `pytest packages/ai-parrot-pipelines/tests/planogram_cycle/test_reporting_projection.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_scoring_projection.py packages/ai-parrot-pipelines/tests/planogram_cycle/test_pos_compliance_characterization.py -q`

---

## Test Specification

Use distinct model/display-name/observed-brand strings so accidental identity fallback cannot pass. Include CLOSEOUT-like three facings, threshold equality and a high-confidence second view following a low-confidence deciding view. Compare all non-label model_dump fields, not selected scores only.

---

## Agent Instructions

1. Use `$sdd-start TASK-4170` to provision the feature worktree; never implement on `dev`.
2. Read the spec and this task; confirm dependencies are done in `sdd/tasks/index/planogram-ink-wall-slot-presence.json`.
3. Reverify imports, signatures and anchors; refresh the contract first if code moved.
4. Implement only the declared files from the blueprint, completing every FILL IN item.
5. Run Validation Commands; store test logs under `artifacts/logs/`. Run black and ruff on touched Python files.
6. Commit scoped code, then finalize using `scripts.sdd.finalize_task` with real
   `TaskCompletionEvidence` and the exact implementation HEAD, per the Codex adaptation contract.
   Do not use the legacy close_task.sh path or manually move this task/change its Completion Note.

## Completion Note

Populated by the task finalizer after implementation and verification.
