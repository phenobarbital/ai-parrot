"""Pinned scoring fixtures and projection status tests (FEAT-574, spec §4)."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import pytest

from parrot.models.compliance import ComplianceStatus
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.comparison.definition import load_slots_definition, validate_bindings
from parrot_pipelines.planogram.comparison.projection import finalize_comparison, project_compliance
from parrot_pipelines.planogram.comparison.registration import ImageRegistration
from parrot_pipelines.planogram.comparison.scoring import merge_positions, score_shelves, summarize
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus,
    ComparisonResult,
    CreditPolicy,
    EvidenceWeights,
    FacingStatus,
    Identification,
    ObservationSource,
    RuleOutcome,
)

BRAND = "Acme"


def _run(definition, description, registrations, identifications, bindings=(), outcomes=None):
    """merge -> score -> summarize -> project -> finalize; returns the final ComparisonResult."""
    policy = CreditPolicy.default()
    positions = merge_positions(definition, registrations, identifications, policy)
    shelves = score_shelves(positions, definition, list(bindings), outcomes or {}, description, policy)
    comparison = summarize(shelves, positions, definition, EvidenceWeights())
    results = project_compliance(shelves, positions, definition, description)
    return finalize_comparison(
        comparison.model_copy(update={"position_results": positions, "shelf_scores": shelves}), results
    )


def _definition(
    shelves: Sequence[Tuple[str, str, int]], undescribed: Dict[str, int] | None = None, zones: List[dict] | None = None
):
    """Definition from ``(shelf_id, level, n_facings)``; ``undescribed[shelf_id]`` = trailing undescribed facings."""
    data = {"version": "1", "shelves": [], "zones": zones or []}
    for number, (shelf_id, level, count) in enumerate(shelves, start=1):
        n_undescribed = (undescribed or {}).get(shelf_id, 0)
        facings = []
        for idx in range(1, count + 1):
            described = idx <= count - n_undescribed
            facings.append(
                {
                    "facing_id": f"{shelf_id}_f{idx}",
                    "shelf_id": shelf_id,
                    "slot": idx,
                    "product": f"{shelf_id.upper()}-{idx}",
                    "brand": BRAND,
                    "descriptors": {"display_name": f"Product {shelf_id} {idx}"} if described else {},
                }
            )
        data["shelves"].append({"shelf_id": shelf_id, "shelf_number": number, "level": level, "facings": facings})
    return load_slots_definition(data)


def _description(levels: Sequence[str], endcap: bool = False):
    """A real PlanogramDescription with one ShelfConfig per level (default weights / threshold)."""
    raw = {
        "brand": BRAND,
        "category": "Test",
        "aisle": {"name": "Test", "lighting_conditions": "normal"},
        "shelves": [{"level": level, "height_ratio": 0.3, "products": []} for level in levels],
    }
    if endcap:
        raw["advertisement_endcap"] = {"enabled": True, "position": "header", "text_requirements": []}
    return PlanogramConfig(planogram_config=raw).get_planogram_description()


def _obs(
    image_id: str,
    shape_id: str,
    product: Optional[str],
    source: str = "cv",
    uncertain: bool = False,
    evidence: Tuple[str, ...] = ("sku text",),
    empty: bool = False,
    brand: Optional[str] = None,
) -> Identification:
    return Identification(
        shape_id=shape_id,
        image_id=image_id,
        product=product,
        brand=brand,
        occupancy="empty" if empty else "occupied",
        evidence=list(evidence) if product else [],
        source=ObservationSource(source),
        uncertain=uncertain,
        raw_confidence=0.9,
    )


def _reg(image_id: str, assignments: Dict[str, str]) -> ImageRegistration:
    return ImageRegistration(image_id=image_id, row_to_shelf={0: "x"}, assignments=assignments)


def _observe(image_id: str, facings: Dict[str, Identification]):
    """Registration + identifications from ``facing_id -> identification`` (shape ids derived)."""
    idents, assignments = [], {}
    for facing_id, ident in facings.items():
        shape_id = f"{image_id}:{facing_id}"
        idents.append(ident.model_copy(update={"shape_id": shape_id, "image_id": image_id}))
        assignments[shape_id] = facing_id
    return _reg(image_id, assignments), idents


def _match_all(definition, image_id="img0", source="cv"):
    return {f.facing_id: _obs(image_id, "", f.product, source=source) for f in definition.all_facings()}


# --------------------------------------------------------------------------- pinned fixtures


def test_scoring_fixture_zero_evidence():
    definition = _definition([("top", "top", 4)])
    description = _description(["top"])
    reg, idents = _observe(
        "img0", {f.facing_id: _obs("img0", "", None, uncertain=True) for f in definition.all_facings()}
    )
    result = _run(definition, description, [reg], idents)
    assert {p.status for p in result.position_results} == {FacingStatus.NOT_ASSESSED}
    assert result.overall_compliance_score == 0.0 and result.strict_compliance_score == 0.0
    assert result.coverage == 0.0
    assert result.assessment_status == AssessmentStatus.INCONCLUSIVE
    assert result.overall_compliant is False

    unregistered = _run(definition, description, [], [])
    assert {p.status for p in unregistered.position_results} == {FacingStatus.NOT_VISIBLE}
    assert unregistered.overall_compliance_score == 0.0 and unregistered.coverage == 0.0
    assert unregistered.overall_compliant is False


def test_scoring_fixture_partial_identity():
    definition = _definition([("top", "top", 10)])
    observed = {}
    for idx, facing in enumerate(definition.all_facings()):
        observed[facing.facing_id] = (
            _obs("img0", "", facing.product) if idx < 6 else _obs("img0", "", None, brand=BRAND)
        )
    reg, idents = _observe("img0", observed)
    result = _run(definition, _description(["top"]), [reg], idents)
    shelf = result.shelf_scores[0]
    assert [p.status for p in result.position_results].count(FacingStatus.VARIANT_UNRESOLVED) == 4
    assert shelf.facing_lenient == pytest.approx(0.8)
    assert shelf.facing_strict == pytest.approx(0.6)
    assert result.coverage == pytest.approx(0.6)
    assert result.assessment_status == AssessmentStatus.INCONCLUSIVE
    assert result.compliance_results[0].compliance_status == ComplianceStatus.NON_COMPLIANT
    assert result.overall_compliant is False


def test_scoring_fixture_incomplete_definition():
    definition = _definition([("top", "top", 10)], undescribed={"top": 4})
    observed = {}
    for idx, facing in enumerate(definition.all_facings()):
        if idx < 6:
            observed[facing.facing_id] = _obs("img0", "", facing.product)
        elif idx < 9:
            observed[facing.facing_id] = _obs("img0", "", None)  # occupied, unreadable
        else:
            observed[facing.facing_id] = _obs("img0", "", facing.product)  # independently readable identifier
    reg, idents = _observe("img0", observed)
    result = _run(definition, _description(["top"]), [reg], idents)
    assert result.definition_coverage == pytest.approx(0.6)
    statuses = [p.status for p in result.position_results]
    assert statuses[6:9] == [FacingStatus.OCCUPIED_UNASSIGNED] * 3
    assert statuses[9] == FacingStatus.MATCH
    assert result.coverage == pytest.approx(0.7)
    assert result.assessment_status == AssessmentStatus.INCONCLUSIVE


def test_scoring_fixture_conflicting_photos():
    definition = _definition([("top", "top", 2)])
    f1, f2 = [f.facing_id for f in definition.all_facings()]
    reg0, idents0 = _observe("img0", {f1: _obs("img0", "", "TOP-1"), f2: _obs("img0", "", "TOP-2")})
    reg1, idents1 = _observe("img1", {f1: _obs("img1", "", "OTHER-9"), f2: _obs("img1", "", None, uncertain=True)})
    result = _run(definition, _description(["top"]), [reg0, reg1], idents0 + idents1)
    first, second = result.position_results
    assert first.status == FacingStatus.CONFLICT
    assert (first.strict_credit, first.lenient_credit) == (0.0, 0.0)
    assert {o.image_id for o in first.observations} == {"img0", "img1"}
    assert second.status == FacingStatus.MATCH  # the unreadable second photo does not create a conflict
    assert len(second.observations) == 2


def test_scoring_fixture_zone_only_shelf():
    zones = [{"zone_id": "zone_backlit", "kind": "backlit", "shelf_id": "header", "required": True}]
    definition = _definition([("header", "header", 0), ("top", "top", 2)], zones=zones)
    bindings = validate_bindings(
        definition,
        {
            "rule_bindings": [
                {"rule_id": "zone", "kind": "zone_present", "target_id": "zone_backlit"},
                {"rule_id": "t1", "kind": "text_requirements", "target_id": "header"},
                {"rule_id": "t2", "kind": "text_requirements", "target_id": "header"},
                {"rule_id": "ill", "kind": "illumination", "target_id": "zone_backlit"},
            ]
        },
    )
    outcomes = {
        "zone": RuleOutcome(rule_id="zone", assessed=True, passed=True, score=1.0),
        "t1": RuleOutcome(rule_id="t1", assessed=True, passed=True, score=1.0),
        "t2": RuleOutcome(rule_id="t2", assessed=True, passed=True, score=0.5),
        "ill": RuleOutcome(
            rule_id="ill",
            assessed=True,
            passed=False,
            score=0.0,
            penalty=0.5,
            detail="Backlit — backlight OFF (required: ON)",
        ),
    }
    reg, idents = _observe("img0", _match_all(definition))
    result = _run(definition, _description(["header", "top"], endcap=True), [reg], idents, bindings, outcomes)
    header = result.shelf_scores[0]
    assert header.expected_facings == 0
    # product_term = zone_score = 1.0 ; text = 0.75 ; header weights 0.64/0.2/(0.16 not applying) -> normalised
    expected = ((1.0 * 0.64 + 0.75 * 0.2) / (0.64 + 0.2)) * (1 - 0.5 / 1)
    assert header.lenient_score == pytest.approx(expected)
    assert header.strict_score == pytest.approx(expected)
    header_result = result.compliance_results[0]
    assert header_result.missing_products == ["Backlit — backlight OFF (required: ON)"]
    assert header_result.compliance_status == ComplianceStatus.NON_COMPLIANT


def test_scoring_fixture_full_llm_fallback():
    definition = _definition([("top", "top", 3)])
    reg, idents = _observe("img0", _match_all(definition, source="llm"))
    result = _run(definition, _description(["top"]), [reg], idents)
    assert result.overall_compliance_score == pytest.approx(1.0)
    assert result.assessment_status == AssessmentStatus.COMPLETE
    assert result.overall_compliant is True
    assert result.evidence_quality == pytest.approx(0.5)
    assert all(o.source == ObservationSource.LLM for p in result.position_results for o in p.observations)


def test_scoring_fixture_weight_normalisation():
    definition = _definition([("top", "top", 10)])
    observed = {}
    for idx, facing in enumerate(definition.all_facings()):
        observed[facing.facing_id] = (
            _obs("img0", "", facing.product) if idx < 8 else _obs("img0", "", None, brand=BRAND)
        )
    bindings = validate_bindings(
        definition,
        {
            "rule_bindings": [
                {"rule_id": "text", "kind": "text_requirements", "target_id": "top"},
                {"rule_id": "visual", "kind": "visual_features", "target_id": "top_f1"},
            ]
        },
    )
    outcomes = {
        "text": RuleOutcome(rule_id="text", assessed=True, passed=True, score=1.0),
        "visual": RuleOutcome(rule_id="visual", assessed=True, passed=True, score=1.0),
    }
    reg, idents = _observe("img0", observed)
    result = _run(definition, _description(["top"]), [reg], idents, bindings, outcomes)
    shelf = result.shelf_scores[0]
    assert shelf.facing_lenient == pytest.approx(0.9)
    assert shelf.lenient_score == pytest.approx((0.9 * 0.8 + 0.1 + 0.2) / 1.1)  # 0.92727…
    assert shelf.lenient_score < 1.0


# --------------------------------------------------------------------------- projection


def test_projection_statuses():
    definition = _definition([("a", "a", 2), ("b", "b", 2), ("c", "c", 2), ("d", "d", 2)])
    observed = {
        "a_f1": _obs("img0", "", "A-1"),
        "a_f2": _obs("img0", "", "A-2"),
        "b_f1": _obs("img0", "", None, empty=True),
        "b_f2": _obs("img0", "", None, empty=True),
        "c_f1": _obs("img0", "", "C-2"),
        "c_f2": _obs("img0", "", "C-1"),
        "d_f1": _obs("img0", "", "D-1"),
        "d_f2": _obs("img0", "", "ZZ-9"),
    }
    reg, idents = _observe("img0", observed)
    result = _run(definition, _description(["a", "b", "c", "d"]), [reg], idents)
    statuses = [r.compliance_status for r in result.compliance_results]
    assert statuses == [
        ComplianceStatus.COMPLIANT,
        ComplianceStatus.MISSING,
        ComplianceStatus.MISPLACED,
        ComplianceStatus.NON_COMPLIANT,
    ]
    assert all(r.assessment is not None for r in result.compliance_results)
    assert result.compliance_results[1].missing_products == ["Product b 1", "Product b 2"]
    assert result.overall_compliant is False


def test_unseen_products_never_in_missing_products():
    definition = _definition([("top", "top", 4)])
    reg, idents = _observe(
        "img0",
        {"top_f1": _obs("img0", "", "TOP-1"), "top_f2": _obs("img0", "", None, uncertain=True)},
    )
    result = _run(definition, _description(["top"]), [reg], idents)
    statuses = [p.status for p in result.position_results]
    assert statuses == [
        FacingStatus.MATCH,
        FacingStatus.NOT_ASSESSED,
        FacingStatus.NOT_VISIBLE,
        FacingStatus.NOT_VISIBLE,
    ]
    shelf = result.compliance_results[0]
    assert shelf.missing_products == []
    assert shelf.compliance_status == ComplianceStatus.NON_COMPLIANT
    assert shelf.assessment.unresolved_facing_ids == ["top_f2", "top_f3", "top_f4"]


def test_empty_result_list_is_never_a_pass():
    comparison = ComparisonResult(assessment_status=AssessmentStatus.COMPLETE, overall_compliance_score=1.0)
    assert finalize_comparison(comparison, []).overall_compliant is False
    assert summarize([], [], _definition([("top", "top", 1)]), EvidenceWeights()).overall_compliance_score == 0.0


def test_coverage_is_global_over_facings_not_mean_of_shelves():
    definition = _definition([("a", "a", 1), ("b", "b", 3)])
    reg, idents = _observe("img0", {"a_f1": _obs("img0", "", "A-1"), "b_f1": _obs("img0", "", "B-1")})
    result = _run(definition, _description(["a", "b"]), [reg], idents)
    assert result.coverage == pytest.approx(2 / 4)
    assert result.coverage != pytest.approx((1.0 + 1 / 3) / 2)


def test_overall_score_is_unweighted_shelf_mean():
    definition = _definition([("a", "a", 1), ("b", "b", 3)])
    observed = {
        "a_f1": _obs("img0", "", "A-1"),
        "b_f1": _obs("img0", "", None, empty=True),
        "b_f2": _obs("img0", "", None, empty=True),
        "b_f3": _obs("img0", "", None, empty=True),
    }
    reg, idents = _observe("img0", observed)
    result = _run(definition, _description(["a", "b"]), [reg], idents)
    assert result.shelf_scores[0].lenient_score == pytest.approx(1.0)
    assert result.shelf_scores[1].lenient_score == pytest.approx(0.0)
    assert result.overall_compliance_score == pytest.approx(0.5)  # not the facing-weighted 0.25
