"""Projection of shelf scores onto the public ComplianceResult vocabulary (FEAT-574)."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence

from parrot.models.compliance import ComplianceResult, ComplianceStatus, ShelfAssessment
from parrot.models.detections import PlanogramDescription

from parrot_pipelines.planogram.comparison.definition import FacingDefinition, SlotsDefinition
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus,
    ComparisonResult,
    FacingStatus,
    PositionResult,
    ShelfScore,
)

logger = logging.getLogger(__name__)

_RESOLVED = {
    FacingStatus.MATCH,
    FacingStatus.MISPLACED,
    FacingStatus.MISMATCH,
    FacingStatus.EMPTY,
    FacingStatus.INFERRED_PRESENT,
    FacingStatus.VARIANT_UNRESOLVED,
}
_FOUND = {
    FacingStatus.MATCH,
    FacingStatus.MISPLACED,
    FacingStatus.MISMATCH,
    FacingStatus.VARIANT_UNRESOLVED,
    FacingStatus.INFERRED_PRESENT,
}
_DEFAULT_THRESHOLD = 0.8


def _label(facing: FacingDefinition) -> str:
    """Human label of an expected facing: its display name, else its product id."""
    return facing.descriptors.display_name or facing.product


def _threshold(description: PlanogramDescription, level: Optional[str]) -> float:
    """Per-shelf compliance threshold (``ShelfConfig.compliance_threshold``), 0.8 without a config."""
    for config in getattr(description, "shelves", None) or []:
        if level is not None and config.level == level:
            return float(config.compliance_threshold)
    return _DEFAULT_THRESHOLD


def project_compliance(
    shelf_scores: Sequence[ShelfScore],
    positions: Sequence[PositionResult],
    definition: SlotsDefinition,
    description: PlanogramDescription,
) -> List[ComplianceResult]:
    """One ComplianceResult per definition shelf, definition order. Sets ``ComplianceResult.assessment``.

    Status rules: COMPLIANT iff completely assessed, facing_lenient >= shelf threshold, no mandatory rule
    failed, no illumination mismatch; MISSING iff completely assessed and every facing is EMPTY; MISPLACED
    iff completely assessed and every violation is MISPLACED; otherwise NON_COMPLIANT. ``missing_products``
    lists only facings proven EMPTY (plus illumination pseudo-entries). ``unexpected_products`` is left
    empty for the type hook to fill (a "major unexpected product" therefore never blocks here).

    ``ShelfScore.rule_results`` (see ``score_shelves``) holds only status-relevant outcomes: a failed entry
    blocks COMPLIANT, an unassessed entry makes the shelf incomplete, and a failed entry with a penalty (only
    illumination rules carry penalties) contributes its ``detail`` as an illumination pseudo-entry.

    Args:
        shelf_scores: Per-shelf scores (definition order).
        positions: Merged positions.
        definition: The slots definition.
        description: The planogram description (per-shelf thresholds).

    Returns:
        One result per definition shelf.
    """
    scores_by_shelf: Dict[str, ShelfScore] = {s.shelf_id: s for s in shelf_scores}
    positions_by_facing: Dict[str, PositionResult] = {p.facing_id: p for p in positions}
    results: List[ComplianceResult] = []
    for shelf in definition.shelves:
        score = scores_by_shelf.get(shelf.shelf_id)
        if score is None:
            logger.debug("project_compliance: no score for %s", shelf.shelf_id)
            continue
        pairs = [(f, positions_by_facing.get(f.facing_id)) for f in shelf.facings]
        statuses = [p.status if p is not None else FacingStatus.NOT_VISIBLE for _, p in pairs]
        unresolved_ids = [
            f.facing_id for f, status in zip(shelf.facings, statuses, strict=True) if status not in _RESOLVED
        ]
        failed_rules = [o for o in score.rule_results if o.assessed and o.passed is False]
        rules_complete = all(o.assessed for o in score.rule_results)
        complete = not unresolved_ids and rules_complete

        missing = [_label(f) for f, status in zip(shelf.facings, statuses, strict=True) if status == FacingStatus.EMPTY]
        missing += [o.detail for o in failed_rules if o.penalty > 0 and o.detail]
        found = [(p.identity or _label(f)) for f, p in pairs if p is not None and p.status in _FOUND]
        threshold = _threshold(description, shelf.level)
        meets_threshold = score.expected_facings == 0 or score.facing_lenient >= threshold
        violations = [s for s in statuses if s != FacingStatus.MATCH]
        if complete and meets_threshold and not failed_rules:
            status = ComplianceStatus.COMPLIANT
        elif complete and statuses and all(s == FacingStatus.EMPTY for s in statuses):
            status = ComplianceStatus.MISSING
        elif complete and not failed_rules and violations and all(s == FacingStatus.MISPLACED for s in violations):
            status = ComplianceStatus.MISPLACED
        else:
            status = ComplianceStatus.NON_COMPLIANT

        assessment = ShelfAssessment(
            assessment_status=(AssessmentStatus.COMPLETE if complete else AssessmentStatus.INCONCLUSIVE).value,
            coverage=score.coverage,
            strict_score=score.strict_score,
            lenient_score=score.lenient_score,
            expected_facings=score.expected_facings,
            resolved_facings=score.expected_facings - len(unresolved_ids),
            unresolved_facing_ids=unresolved_ids,
            rule_results=[o.model_dump(mode="json") for o in score.rule_results],
        )
        results.append(
            ComplianceResult(
                shelf_level=score.shelf_level,
                expected_products=[_label(f) for f in shelf.facings],
                found_products=found,
                missing_products=missing,
                unexpected_products=[],
                compliance_status=status,
                compliance_score=max(0.0, min(1.0, score.lenient_score)),
                assessment=assessment,
            )
        )
    return results


def finalize_comparison(
    comparison: ComparisonResult, compliance_results: Sequence[ComplianceResult]
) -> ComparisonResult:
    """Attach the projected results and decide ``overall_compliant``.

    True only when the assessment is COMPLETE, the list is non-empty and every shelf is COMPLIANT.

    Args:
        comparison: Output of ``summarize`` (with positions / shelf scores attached by the caller).
        compliance_results: Output of ``project_compliance``.

    Returns:
        A copy with ``compliance_results`` and ``overall_compliant`` set.
    """
    compliant = bool(
        compliance_results
        and comparison.assessment_status == AssessmentStatus.COMPLETE
        and all(r.compliance_status == ComplianceStatus.COMPLIANT for r in compliance_results)
    )
    return comparison.model_copy(
        update={"compliance_results": list(compliance_results), "overall_compliant": compliant}
    )
