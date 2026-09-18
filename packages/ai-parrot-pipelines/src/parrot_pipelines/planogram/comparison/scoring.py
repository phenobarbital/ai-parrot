"""Per-facing decision, multi-photo merge and scoring for migrated planogram types (FEAT-574)."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Sequence, Set, Tuple

from parrot.models.detections import PlanogramDescription, ShelfConfig

from parrot_pipelines.planogram.comparison.definition import (
    FacingDefinition,
    RuleBinding,
    ShelfDefinition,
    SlotsDefinition,
    definition_coverage,
)
from parrot_pipelines.planogram.comparison.registration import ImageRegistration
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus,
    ComparisonResult,
    CreditPolicy,
    EvidenceWeights,
    FacingStatus,
    Identification,
    ObservationRef,
    PositionResult,
    RuleOutcome,
    ShelfScore,
)

logger = logging.getLogger(__name__)

_DEFAULT_VISUAL_WEIGHT = 0.2
_DEFAULT_TEXT_WEIGHT = 0.1
_HEADER_VISUAL_SHARE = 0.2  # header/endcap: visual weight = endcap.product_weight * 0.2 (today's rule)

_RESOLVED = {FacingStatus.MATCH, FacingStatus.MISPLACED, FacingStatus.MISMATCH, FacingStatus.EMPTY}
_OCCUPIED = {
    FacingStatus.MATCH,
    FacingStatus.MISPLACED,
    FacingStatus.VARIANT_UNRESOLVED,
    FacingStatus.MISMATCH,
    FacingStatus.INFERRED_PRESENT,
    FacingStatus.OCCUPIED_UNASSIGNED,
}


def _norm(text: Optional[str]) -> Optional[str]:
    """Casefold/strip a token; None or empty stays None."""
    return text.casefold().strip() if text and text.strip() else None


def _is_admissible(obs: Identification) -> bool:
    """Not uncertain, product set, and at least one piece of crop-tied evidence."""
    return bool(not obs.uncertain and obs.product and obs.evidence)


def _is_reliable(obs: Identification) -> bool:
    """A usable observation: not uncertain and saying something (occupancy, product or brand)."""
    if obs.uncertain:
        return False
    return obs.occupancy in ("occupied", "empty") or bool(obs.product) or bool(obs.brand)


def _is_empty(obs: Identification) -> bool:
    """Empty is signalled only by ``occupancy == "empty"`` ("unknown" is never empty)."""
    return obs.occupancy == "empty"


def _decide(
    facing: FacingDefinition, views: Sequence[Identification], matched_elsewhere_on_shelf: bool
) -> Tuple[FacingStatus, Optional[Identification]]:
    """Apply the 10-step decision list of the task Scope. Returns (status, deciding observation).

    ``source`` is never consulted: evidence weights only feed ``evidence_quality``.
    """
    # 1. nothing registered
    if not views:
        return FacingStatus.NOT_VISIBLE, None
    # 2. nothing reliable (uncertain / unreadable only)
    reliable = [v for v in views if _is_reliable(v)]
    if not reliable:
        return FacingStatus.NOT_ASSESSED, None
    occupied = [v for v in reliable if not _is_empty(v)]
    empty = [v for v in reliable if _is_empty(v)]
    admissible = [v for v in occupied if _is_admissible(v)]
    products = {_norm(v.product) for v in admissible}
    # 3. reliable disagreement
    if (occupied and empty) or len(products) >= 2:
        return FacingStatus.CONFLICT, None
    # 4. every reliable view says empty
    if not occupied:
        return FacingStatus.EMPTY, empty[0]
    expected = _norm(facing.product)
    # 5. exact identity
    for view in admissible:
        if _norm(view.product) == expected:
            return FacingStatus.MATCH, view
    # 6. expected product seen at another facing of the same shelf
    if matched_elsewhere_on_shelf:
        return FacingStatus.MISPLACED, admissible[0] if admissible else occupied[0]
    expected_brand = _norm(facing.brand)
    expected_family = _norm(facing.descriptors.family)
    # 7. brand (and family) agree, exact product not established
    if not admissible and expected_brand:
        for view in occupied:
            if _norm(view.brand) != expected_brand:
                continue
            observed_family = _norm(str(view.descriptors.get("family") or "") or None)
            if expected_family and observed_family and observed_family != expected_family:
                continue
            return FacingStatus.VARIANT_UNRESOLVED, view
    # 8. a different admissible product, or a different brand
    if admissible:
        return FacingStatus.MISMATCH, admissible[0]
    if expected_brand:
        for view in occupied:
            observed_brand = _norm(view.brand)
            if observed_brand and observed_brand != expected_brand:
                return FacingStatus.MISMATCH, view
    # 9. occupied facing the definition does not describe
    if not facing.descriptors.sufficient:
        return FacingStatus.OCCUPIED_UNASSIGNED, occupied[0]
    # 10. occupied without identity evidence
    return FacingStatus.INFERRED_PRESENT, occupied[0]


def _ref(obs: Identification) -> ObservationRef:
    """Provenance record of one observation."""
    return ObservationRef(
        image_id=obs.image_id or "",
        shape_id=obs.shape_id,
        source=obs.source,
        raw_confidence=obs.raw_confidence,
        product=obs.product,
    )


def merge_positions(
    definition: SlotsDefinition,
    registrations: Sequence[ImageRegistration],
    identifications: Sequence[Identification],
    policy: CreditPolicy,
) -> List[PositionResult]:
    """One PositionResult per expected facing, merging every image's registered observations.

    ``Identification.product`` must already be the canonical product id of the definition.
    Ambiguous registrations contribute nothing (their facings stay not_visible / not_assessed).
    The deciding observation (when any) is the FIRST entry of ``PositionResult.observations``;
    every other registered view follows, so all provenance is kept.

    Args:
        definition: The slots definition.
        registrations: One registration per image.
        identifications: Identifications of every image.
        policy: Credit policy.

    Returns:
        Position results in definition order.
    """
    views: Dict[str, List[Identification]] = {}
    by_key = {(i.image_id, i.shape_id): i for i in identifications}
    for reg in registrations:
        if reg.ambiguous:
            continue
        for shape_id, facing_id in reg.assignments.items():
            obs = by_key.get((reg.image_id, shape_id))
            if obs is not None:
                views.setdefault(facing_id, []).append(obs)

    # First pass: admissible product ids seen at each facing (for `misplaced`).
    seen: Dict[str, Set[str]] = {}
    for facing in definition.all_facings():
        ids = {
            _norm(v.product)
            for v in views.get(facing.facing_id, [])
            if _is_reliable(v) and not _is_empty(v) and _is_admissible(v)
        }
        seen[facing.facing_id] = {i for i in ids if i}

    results: List[PositionResult] = []
    for shelf in definition.shelves:
        for facing in shelf.facings:
            expected = _norm(facing.product)
            elsewhere = any(
                expected in seen[other.facing_id] for other in shelf.facings if other.facing_id != facing.facing_id
            )
            facing_views = views.get(facing.facing_id, [])
            status, deciding = _decide(facing, facing_views, elsewhere)
            ordered = ([deciding] if deciding is not None else []) + [v for v in facing_views if v is not deciding]
            identity = None
            if deciding is not None and status in _OCCUPIED:
                identity = deciding.product or deciding.brand
            notes = [f"deciding:{deciding.image_id}/{deciding.shape_id}"] if deciding is not None else []
            results.append(
                PositionResult(
                    facing_id=facing.facing_id,
                    shelf_id=shelf.shelf_id,
                    status=status,
                    strict_credit=policy.strict[status],
                    lenient_credit=policy.lenient[status],
                    identity=identity,
                    observations=[_ref(v) for v in ordered],
                    notes=notes,
                )
            )
    return results


def _weights(
    shelf: ShelfDefinition,
    config: Optional[ShelfConfig],
    description: PlanogramDescription,
    applies: Tuple[bool, bool, bool],
) -> Tuple[float, float, float]:
    """Normalised (Wp', Wt', Wv') over the terms that apply (product, text, visual).

    Args:
        shelf: The definition shelf.
        config: Its ``ShelfConfig`` (matched by level), if any.
        description: The planogram description (advertisement endcap).
        applies: Whether the product, text and visual terms apply to the shelf.

    Returns:
        Weights summing to 1.0 over the applying terms (all zero when no term applies).
    """
    endcap = getattr(description, "advertisement_endcap", None)
    is_header = bool(
        endcap is not None
        and getattr(endcap, "enabled", False)
        and shelf.level is not None
        and getattr(endcap, "position", None) == shelf.level
    )
    if is_header:
        product_weight = float(endcap.product_weight)
        wp = product_weight * (1 - _HEADER_VISUAL_SHARE)
        wt = float(endcap.text_weight)
        wv = product_weight * _HEADER_VISUAL_SHARE
    else:
        visual = getattr(config, "visual_weight", None) if config is not None else None
        text = getattr(config, "text_weight", None) if config is not None else None
        product = getattr(config, "product_weight", None) if config is not None else None
        wv = visual if visual is not None else _DEFAULT_VISUAL_WEIGHT
        wt = text if text is not None else _DEFAULT_TEXT_WEIGHT
        wp = product if product is not None else (1 - wv)
    raw = [w if apply else 0.0 for w, apply in zip((wp, wt, wv), applies, strict=True)]
    total = sum(raw)
    if total <= 0:
        return 0.0, 0.0, 0.0
    return raw[0] / total, raw[1] / total, raw[2] / total


def _shelf_of_target(definition: SlotsDefinition) -> Dict[str, Optional[str]]:
    """Map every stable id (facing / zone / shelf) to its shelf id."""
    mapping: Dict[str, Optional[str]] = {}
    for shelf in definition.shelves:
        mapping[shelf.shelf_id] = shelf.shelf_id
        for facing in shelf.facings:
            mapping[facing.facing_id] = shelf.shelf_id
    for zone in definition.zones:
        mapping[zone.zone_id] = zone.shelf_id
    return mapping


def _clamp01(value: float) -> float:
    """Clamp to [0, 1]."""
    return max(0.0, min(1.0, value))


def _combine(
    product_term: float,
    text_score: float,
    visual_score: float,
    weights: Tuple[float, float, float],
    multiplier: float,
) -> float:
    """``clamp01((product·Wp' + text·Wt' + visual·Wv') · multiplier)`` — the penalty is applied once."""
    wp, wt, wv = weights
    return _clamp01((product_term * wp + text_score * wt + visual_score * wv) * multiplier)


def _mean_scores(outcomes: Sequence[RuleOutcome]) -> float:
    """Mean score of assessed outcomes; unassessed ones earn nothing (0.0)."""
    if not outcomes:
        return 1.0
    return sum(o.score if o.assessed else 0.0 for o in outcomes) / len(outcomes)


def score_shelves(
    positions: Sequence[PositionResult],
    definition: SlotsDefinition,
    bindings: Sequence[RuleBinding],
    rule_outcomes: Dict[str, RuleOutcome],
    description: PlanogramDescription,
    policy: CreditPolicy,
) -> List[ShelfScore]:
    """One ShelfScore per definition shelf, in definition order (formula of the task Scope).

    ``ShelfScore.rule_results`` carries the outcomes that decide status/completeness: every MANDATORY
    binding (an unassessed placeholder when no outcome was supplied) plus every assessed illumination
    binding. Illumination penalties are the only penalties the formula applies.

    Args:
        positions: Merged positions.
        definition: The slots definition.
        bindings: Validated rule bindings.
        rule_outcomes: Outcome per ``rule_id``.
        description: The planogram description (weights, endcap).
        policy: Credit policy (credits are already on the positions; kept for signature stability).

    Returns:
        Shelf scores in definition order.
    """
    target_shelf = _shelf_of_target(definition)
    by_shelf: Dict[str, List[PositionResult]] = {}
    for position in positions:
        by_shelf.setdefault(position.shelf_id, []).append(position)
    configs = {c.level: c for c in (getattr(description, "shelves", None) or [])}

    scores: List[ShelfScore] = []
    for shelf in definition.shelves:
        shelf_bindings = [b for b in bindings if target_shelf.get(b.target_id) == shelf.shelf_id]
        outcomes = {
            b.rule_id: rule_outcomes.get(b.rule_id) or RuleOutcome(rule_id=b.rule_id, detail="not evaluated")
            for b in shelf_bindings
        }
        texts = [outcomes[b.rule_id] for b in shelf_bindings if b.kind == "text_requirements"]
        visuals = [outcomes[b.rule_id] for b in shelf_bindings if b.kind == "visual_features"]
        illumination = [outcomes[b.rule_id] for b in shelf_bindings if b.kind == "illumination"]

        facings = by_shelf.get(shelf.shelf_id, [])
        count = len(facings)
        facing_strict = sum(p.strict_credit for p in facings) / count if count else 0.0
        facing_lenient = sum(p.lenient_credit for p in facings) / count if count else 0.0

        required_zones = [z for z in definition.zones if z.shelf_id == shelf.shelf_id and z.required]
        zone_score = 0.0
        if required_zones:
            observed = 0
            for zone in required_zones:
                zone_rules = [
                    outcomes[b.rule_id]
                    for b in shelf_bindings
                    if b.kind == "zone_present" and b.target_id == zone.zone_id
                ]
                if any(o.assessed and o.passed for o in zone_rules):
                    observed += 1
            zone_score = observed / len(required_zones)

        applies = (count > 0 or bool(required_zones), bool(texts), bool(visuals))
        config = configs.get(shelf.level) if shelf.level is not None else None
        if config is None:
            logger.debug("score_shelves: no ShelfConfig for %s; using non-header defaults", shelf.shelf_id)
        wp, wt, wv = _weights(shelf, config, description, applies)
        text_score = _mean_scores(texts)
        visual_score = _mean_scores(visuals)
        penalty = sum(o.penalty for o in illumination if o.assessed and o.passed is False) / max(1, count)
        multiplier = max(0.0, 1 - penalty)

        strict_term = facing_strict if count else zone_score
        lenient_term = facing_lenient if count else zone_score
        resolved = sum(1 for p in facings if policy.is_resolved(p.status))
        visible = sum(1 for p in facings if p.status != FacingStatus.NOT_VISIBLE)
        occupied = sum(1 for p in facings if p.status in _OCCUPIED)
        rule_results = [
            outcomes[b.rule_id]
            for b in shelf_bindings
            if b.mandatory or (b.kind == "illumination" and outcomes[b.rule_id].assessed)
        ]
        scores.append(
            ShelfScore(
                shelf_id=shelf.shelf_id,
                shelf_level=shelf.level or shelf.shelf_id,
                expected_facings=count,
                facing_strict=facing_strict,
                facing_lenient=facing_lenient,
                strict_score=_combine(strict_term, text_score, visual_score, (wp, wt, wv), multiplier),
                lenient_score=_combine(lenient_term, text_score, visual_score, (wp, wt, wv), multiplier),
                coverage=resolved / count if count else 1.0,
                visible_fraction=visible / count if count else 0.0,
                occupied_fraction=occupied / count if count else 0.0,
                rule_results=rule_results,
            )
        )
    return scores


def summarize(
    shelf_scores: Sequence[ShelfScore],
    positions: Sequence[PositionResult],
    definition: SlotsDefinition,
    weights: EvidenceWeights,
) -> ComparisonResult:
    """Global measures. ``compliance_results`` is left empty and ``overall_compliant`` False —
    the projection helper ``finalize_comparison`` sets both.

    Args:
        shelf_scores: Per-shelf scores.
        positions: Merged positions.
        definition: The slots definition.
        weights: Evidence weights (evidence quality only — never credits).

    Returns:
        The comparison result (without projected compliance results).
    """
    if shelf_scores:
        overall = sum(s.lenient_score for s in shelf_scores) / len(shelf_scores)
        strict = sum(s.strict_score for s in shelf_scores) / len(shelf_scores)
    else:
        overall, strict = 0.0, 0.0
    resolved = [p for p in positions if p.status in _RESOLVED]
    coverage = len(resolved) / len(positions) if positions else None
    deciding_weights = [weights.weight_for(p.observations[0].source) for p in resolved if p.observations]
    evidence_quality = sum(deciding_weights) / len(deciding_weights) if deciding_weights else None
    rules_complete = all(o.assessed for s in shelf_scores for o in s.rule_results)
    complete = bool(shelf_scores) and len(resolved) == len(positions) and rules_complete
    return ComparisonResult(
        overall_compliance_score=overall,
        strict_compliance_score=strict,
        overall_compliant=False,
        coverage=coverage,
        definition_coverage=definition_coverage(definition)[0],
        evidence_quality=evidence_quality,
        assessment_status=AssessmentStatus.COMPLETE if complete else AssessmentStatus.INCONCLUSIVE,
    )
