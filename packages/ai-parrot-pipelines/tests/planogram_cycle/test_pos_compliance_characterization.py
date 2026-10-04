"""Regression tests: ProductOnShelves business rules on the perceive -> identify -> compare cycle (FEAT-612).

Replaces the FEAT-574 legacy characterization. Pins retained behaviour (shelf order, facing statuses and
credits, thresholds, zone and text rules, illumination), never legacy score formulas (spec section 4).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import MagicMock

import pytest

from parrot.models.detections import DetectionBox, PlanogramDescription
from parrot.models.detections import AisleConfig, ShelfConfig
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus,
    ComparisonResult,
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FacingStatus,
    FixtureMembership,
    Identification,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    Shape,
    ShapeKind,
    Slot,
)
from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves


class _RaisingVision:
    """Any attribute access or call proves compare() tried to use the vision adapter (AC8)."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"compare() must not touch vision ({name})")


def definition(shelves: Dict[str, List[str]], zones: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Raw definition: ``{"top": ["P-100", "P-200"], ...}`` in top-to-bottom order; generic labels only."""
    rows = []
    for number, (level, products) in enumerate(shelves.items()):
        facings = [
            {
                "facing_id": f"{level}:{slot}",
                "shelf_id": level,
                "slot": slot,
                "product": product,
                "brand": "Acme",
                "descriptors": {"display_name": product, "identifiers": [product]},
            }
            for slot, product in enumerate(products, start=1)
        ]
        rows.append({"shelf_id": level, "shelf_number": number, "level": level, "facings": facings})
    return {"shelves": rows, "zones": list(zones)}


def handler(raw_definition: Dict[str, Any], threshold: Optional[float] = None) -> ProductOnShelves:
    """ProductOnShelves over a MagicMock pipeline with a minimal migrated configuration."""
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.pos.regression")
    pipeline.reference_images = {}
    config = MagicMock()
    config.planogram_config = {"brand": "Acme"}
    config.slots_definition = raw_definition
    if threshold is None:
        config.get_planogram_description.side_effect = ValueError("no legacy shelves")
    else:
        config.get_planogram_description.return_value = PlanogramDescription(
            brand="Acme",
            category="generic",
            aisle=AisleConfig(name="aisle"),
            shelves=[
                ShelfConfig(level=shelf["level"], products=[], compliance_threshold=threshold)
                for shelf in raw_definition["shelves"]
            ],
        )
    return ProductOnShelves(pipeline=pipeline, config=config)


def ctx(raw_definition: Dict[str, Any], bindings: Sequence[Dict[str, Any]] = ()) -> CycleContext:
    """Deterministic context: default credits/weights, POS default layout, vision that raises."""
    return CycleContext(
        definition=load_slots_definition(raw_definition),
        bindings=[RuleBinding(**binding) for binding in bindings],
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
        layout=ProductOnShelves.default_layout_profile(),
        vision=_RaisingVision(),
    )


def observe(
    rows: List[List[Optional[str]]],
    image_id: str = "img0",
    membership: FixtureMembership = FixtureMembership.ON_FIXTURE,
    extra_shapes: Sequence[Shape] = (),
    brand: str = "Acme",
) -> tuple[PerceptionResult, IdentificationResult]:
    """One product shape + slot per cell; ``None`` = observed empty; row 0 is the top row."""
    shapes: List[Shape] = []
    slots: List[Slot] = []
    idents: List[Identification] = []
    for r, row in enumerate(rows):
        for s, label in enumerate(row, start=1):
            shape_id = f"{image_id}:p{r}_{s}"
            slot_id = f"{image_id}:r{r}:s{s}"
            box = DetectionBox(
                x1=20 + 150 * (s - 1), y1=100 + 200 * r, x2=150 + 150 * (s - 1), y2=250 + 200 * r, confidence=0.9
            )
            shapes.append(
                Shape(
                    shape_id=shape_id,
                    image_id=image_id,
                    kind=ShapeKind.PRODUCT,
                    box=box,
                    row_index=r,
                    slot_index=s,
                    membership=membership,
                )
            )
            slots.append(
                Slot(slot_id=slot_id, image_id=image_id, row_index=r, slot_index=s, box=box, anchor_shape_id=shape_id)
            )
            idents.append(
                Identification(
                    shape_id=slot_id,
                    image_id=image_id,
                    product=label,
                    brand=brand if label else None,
                    occupancy="occupied" if label else "empty",
                    raw_confidence=0.9,
                    evidence=[f"reads {label}"] if label else ["empty slot"],
                )
            )
    perception = PerceptionResult(
        image_id=image_id,
        image_size=(1000, 1000),
        shapes=[*shapes, *extra_shapes],
        slots=slots,
        zones=[shape for shape in extra_shapes if shape.kind == ShapeKind.ZONE],
        row_count=len(rows),
    )
    return perception, IdentificationResult(image_id=image_id, identifications=idents)


def zone_shape(image_id: str = "img0", ocr_text: Optional[str] = None) -> Shape:
    """A header zone above the product rows."""
    return Shape(
        shape_id=f"{image_id}:zone",
        image_id=image_id,
        kind=ShapeKind.ZONE,
        box=DetectionBox(x1=10, y1=5, x2=600, y2=80, confidence=0.9),
        ocr_text=ocr_text,
        membership=FixtureMembership.ON_FIXTURE,
    )


async def _compare(h: ProductOnShelves, c: CycleContext, *images: Any) -> ComparisonResult:
    """Run compare() over ``(perception, identification)`` pairs."""
    return await h.compare([p for p, _ in images], [i for _, i in images], c)


def with_observations(ident: IdentificationResult, observations: Sequence[RuleObservation]) -> IdentificationResult:
    """Attach rule observations to an identification result."""
    return ident.model_copy(update={"rule_observations": list(observations)})


def illumination(value: Optional[str], image_id: str = "img0", assessed: bool = True) -> RuleObservation:
    """An illumination observation of the header zone."""
    return RuleObservation(
        image_id=image_id,
        target_id=f"{image_id}:zone",
        kind="illumination",
        value=value,
        assessed=assessed,
        source=ObservationSource.LLM,
    )


HEADER_ZONE = {"zone_id": "zone_backlit", "kind": "backlit", "shelf_id": "header", "required": True}


def _status(result: ComparisonResult) -> Dict[str, FacingStatus]:
    """Facing id to status."""
    return {position.facing_id: position.status for position in result.position_results}


async def test_one_result_per_definition_shelf_in_definition_order() -> None:
    raw = definition({"top": ["P-100"], "middle": ["P-200"], "bottom": ["P-300"]})
    result = await _compare(handler(raw), ctx(raw), observe([["P-100"], ["P-200"], ["P-300"]]))
    assert [r.shelf_level for r in result.compliance_results] == ["top", "middle", "bottom"]


async def test_fully_matched_shelf_is_compliant_and_complete() -> None:
    raw = definition({"top": ["P-100", "P-200"]})
    result = await _compare(handler(raw), ctx(raw), observe([["P-100", "P-200"]]))
    shelf = result.compliance_results[0]
    assert shelf.compliance_status.value == "compliant"
    assert shelf.assessment.assessment_status == "complete"
    assert result.assessment_status == AssessmentStatus.COMPLETE
    assert result.overall_compliant is True
    assert all(p.status == FacingStatus.MATCH for p in result.position_results)
    assert all(p.strict_credit == 1.0 and p.lenient_credit == 1.0 for p in result.position_results)


async def test_empty_facing_is_missing_and_stays_in_denominator() -> None:
    raw = definition({"top": ["P-100", "P-200"]})
    result = await _compare(handler(raw), ctx(raw), observe([["P-100", None]]))
    shelf = result.compliance_results[0]
    positions = {p.facing_id: p for p in result.position_results}
    assert shelf.missing_products == ["P-200"]
    assert positions["top:2"].status == FacingStatus.EMPTY
    assert positions["top:2"].strict_credit == 0.0 and positions["top:2"].lenient_credit == 0.0
    assert result.shelf_scores[0].expected_facings == 2
    assert result.shelf_scores[0].facing_lenient == pytest.approx(0.5)
    assert result.overall_compliant is False


@pytest.mark.parametrize("threshold,expected", [(0.8, "non_compliant"), (0.7, "compliant")])
async def test_threshold_decides_status_on_the_same_evidence(threshold: float, expected: str) -> None:
    raw = definition({"top": ["P-100", "P-200", "P-300", "P-400"]})
    observed = observe([["P-100", "P-200", "P-300", None]])
    result = await _compare(handler(raw, threshold=threshold), ctx(raw), observed)
    assert result.shelf_scores[0].facing_lenient == pytest.approx(0.75)
    assert result.compliance_results[0].compliance_status.value == expected


async def test_expected_product_seen_at_another_facing_is_misplaced_half_credit() -> None:
    raw = definition({"top": ["P-100", "P-200", "P-300"]})
    result = await _compare(handler(raw), ctx(raw), observe([["P-300", "P-200", "P-100"]]))
    positions = {p.facing_id: p for p in result.position_results}
    assert _status(result) == {
        "top:1": FacingStatus.MISPLACED,
        "top:2": FacingStatus.MATCH,
        "top:3": FacingStatus.MISPLACED,
    }
    misplaced = [positions["top:1"], positions["top:3"]]
    for position in misplaced:
        assert position.strict_credit == 0.0
        assert position.lenient_credit == pytest.approx(0.5)


async def test_different_product_at_expected_slot_is_mismatch() -> None:
    raw = definition({"top": ["P-100", "P-200"]})
    observed = observe([["P-100", "P-999"]], brand="Other")
    result = await _compare(handler(raw), ctx(raw), observed)
    positions = {p.facing_id: p for p in result.position_results}
    assert positions["top:2"].status == FacingStatus.MISMATCH
    assert positions["top:2"].strict_credit == 0.0 and positions["top:2"].lenient_credit == 0.0
    assert result.compliance_results[0].compliance_status.value != "compliant"


async def test_zone_only_header_with_unassessed_mandatory_rule_is_inconclusive() -> None:
    raw = definition({"header": []}, zones=[HEADER_ZONE])
    bindings = [{"rule_id": "zone", "kind": "zone_present", "target_id": "zone_backlit"}]
    perception, ident = observe([])
    result = await _compare(handler(raw), ctx(raw, bindings), (perception, ident))
    header = result.compliance_results[0]
    assert header.assessment.assessment_status == "inconclusive"
    assert header.compliance_status.value != "compliant"
    assert result.overall_compliant is False


def _text_binding() -> List[Dict[str, Any]]:
    return [
        {"rule_id": "zone", "kind": "zone_present", "target_id": "zone_backlit"},
        {
            "rule_id": "text",
            "kind": "text_requirements",
            "target_id": "zone_backlit",
            "params": {
                "requirements": [
                    {"required_text": "MANDATORY WORDS", "mandatory": True},
                    {"required_text": "optional words", "mandatory": False},
                ]
            },
        },
    ]


@pytest.mark.parametrize("ocr_text,passed", [("optional words only", False), ("mandatory words only", True)])
async def test_mandatory_text_requirement_miss_fails_optional_does_not(ocr_text: str, passed: bool) -> None:
    raw = definition({"header": []}, zones=[HEADER_ZONE])
    observed = observe([], extra_shapes=[zone_shape(ocr_text=ocr_text)])
    result = await _compare(handler(raw), ctx(raw, _text_binding()), observed)
    outcomes = {o.rule_id: o for o in result.shelf_scores[0].rule_results}
    assert outcomes["text"].assessed is True
    assert outcomes["text"].passed is passed
    assert (result.compliance_results[0].compliance_status.value == "compliant") is passed


async def test_illumination_mismatch_penalty_applied_once() -> None:
    raw = definition({"header": []}, zones=[HEADER_ZONE])
    bindings = [
        {"rule_id": "zone", "kind": "zone_present", "target_id": "zone_backlit"},
        {
            "rule_id": "ill",
            "kind": "illumination",
            "target_id": "zone_backlit",
            "params": {"required": "on", "penalty": 0.5},
        },
    ]
    perception, ident = observe([], extra_shapes=[zone_shape()])
    ident = with_observations(ident, [illumination("off")])
    result = await _compare(handler(raw), ctx(raw, bindings), (perception, ident))
    score = result.shelf_scores[0]
    assert score.lenient_score == pytest.approx(0.5)
    assert result.compliance_results[0].compliance_status.value != "compliant"
    assert len([o for o in result.compliance_results[0].missing_products if "backlight" in o]) == 1
