"""Offline tests for ProductOnShelves.compare and rule evaluation (FEAT-574, TASK-3446)."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus,
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FacingStatus,
    FixtureMembership,
    Identification,
    IdentificationResult,
    PerceptionResult,
    Shape,
    ShapeKind,
    Slot,
)
from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves

IMAGE = Image.new("RGB", (400, 400), "white")


def _definition(with_header: bool = True):
    shelves = []
    zones = []
    if with_header:
        shelves.append({"shelf_id": "header", "shelf_number": 0, "level": "header", "facings": []})
        zones.append({"zone_id": "zone_backlit", "kind": "backlit", "shelf_id": "header", "required": True})
    shelves.append(
        {
            "shelf_id": "top",
            "shelf_number": 1,
            "level": "top",
            "facings": [
                {
                    "facing_id": f"top_f{i}",
                    "shelf_id": "top",
                    "slot": i,
                    "product": f"ES-{i}00",
                    "brand": "Acme",
                    "descriptors": {"display_name": f"ES-{i}00", "identifiers": [f"ES-{i}00"]},
                }
                for i in (1, 2)
            ],
        }
    )
    return load_slots_definition({"shelves": shelves, "zones": zones})


@pytest.fixture
def handler() -> ProductOnShelves:
    """ProductOnShelves with MagicMock pipeline/config."""
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.pos.compare")
    pipeline.reference_images = {}
    config = MagicMock()
    config.planogram_config = {"brand": "Acme"}
    config.object_identification_prompt = None
    config.roi_detection_prompt = None  # migrated type: prompts are not required any more
    config.slots_definition = {"shelves": []}
    config.get_planogram_description.side_effect = ValueError("no legacy shelves")
    return ProductOnShelves(pipeline=pipeline, config=config)


def _ctx(definition, bindings=()) -> CycleContext:
    return CycleContext(
        definition=definition,
        bindings=list(bindings),
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
    )


def _zone(ocr_text=None, membership=FixtureMembership.ON_FIXTURE) -> Shape:
    return Shape(
        shape_id="img0:zone",
        image_id="img0",
        kind=ShapeKind.ZONE,
        box=DetectionBox(x1=10, y1=10, x2=390, y2=80, confidence=0.9),
        ocr_text=ocr_text,
        membership=membership,
    )


def _perception(zone=None, products=("ES-100", "ES-200")) -> PerceptionResult:
    shapes, slots = [], []
    for n, _product in enumerate(products, start=1):
        shape_id = f"img0:p{n}"
        box = DetectionBox(x1=20 + 150 * (n - 1), y1=150, x2=150 + 150 * (n - 1), y2=300, confidence=0.9)
        shapes.append(
            Shape(
                shape_id=shape_id,
                image_id="img0",
                kind=ShapeKind.PRODUCT,
                box=box,
                row_index=0,
                slot_index=n,
                membership=FixtureMembership.ON_FIXTURE,
            )
        )
        slots.append(
            Slot(slot_id=f"img0:r0:s{n}", image_id="img0", row_index=0, slot_index=n, box=box, anchor_shape_id=shape_id)
        )
    return PerceptionResult(
        image_id="img0", image_size=(400, 400), shapes=shapes, slots=slots, zones=[zone] if zone else [], row_count=1
    )


def _identifications(products=("ES-100", "ES-200")) -> IdentificationResult:
    return IdentificationResult(
        image_id="img0",
        identifications=[
            Identification(shape_id=f"img0:r0:s{n}", image_id="img0", product=p, brand="Acme", evidence=[f"reads {p}"])
            for n, p in enumerate(products, start=1)
        ],
    )


def _set_context(handler, definition, perception, registrations=()):
    handler._rule_context = {
        "definition": definition,
        "perceptions": [perception],
        "registrations": list(registrations),
        "identifications": {},
        "slots": {},
    }


async def test_illumination_mismatch_sets_penalty(handler):
    handler._check_illumination = AsyncMock(return_value="illumination_status: OFF")
    definition = _definition()
    _set_context(handler, definition, _perception(_zone()))
    binding = RuleBinding(rule_id="ill", kind="illumination", target_id="zone_backlit", params={"required": "on"})
    out = await handler._evaluate_rules([binding], {"img0": IMAGE}, [], _ctx(definition))
    assert out["ill"].assessed is True and out["ill"].passed is False
    assert out["ill"].penalty == pytest.approx(0.5)
    assert "backlight OFF (required: ON)" in out["ill"].detail
    handler._check_illumination.assert_awaited_once()


async def test_illumination_unknown_is_unassessed(handler):
    handler._check_illumination = AsyncMock(return_value=None)
    definition = _definition()
    _set_context(handler, definition, _perception(_zone()))
    binding = RuleBinding(rule_id="ill", kind="illumination", target_id="zone_backlit", params={"required": "on"})
    out = await handler._evaluate_rules([binding], {"img0": IMAGE}, [], _ctx(definition))
    assert out["ill"].assessed is False and out["ill"].passed is None and out["ill"].penalty == 0.0


def test_text_rule_score_and_mandatory(handler):
    """2 requirements, 1 found with confidence 1.0 → score 0.5; mandatory missing → passed False."""
    definition = _definition()
    _set_context(handler, definition, _perception(_zone(ocr_text="Hello Savings today")))
    params = {
        "requirements": [
            {"required_text": "Hello Savings", "match_type": "contains", "mandatory": False},
            {"required_text": "Goodbye Cartridges", "match_type": "contains", "mandatory": True},
        ]
    }
    outcome = handler._rule_text(
        RuleBinding(rule_id="t", kind="text_requirements", target_id="zone_backlit", params=params), []
    )
    assert outcome.assessed and outcome.score == pytest.approx(0.5)
    assert outcome.passed is False and "Goodbye Cartridges" in outcome.detail
    _set_context(handler, definition, _perception(None))
    unseen = handler._rule_text(
        RuleBinding(rule_id="t", kind="text_requirements", target_id="zone_backlit", params=params), []
    )
    assert unseen.assessed is False


def test_visual_rule_uses_calculate_visual_feature_match(handler):
    definition = _definition()
    _set_context(handler, definition, _perception(_zone(ocr_text="illuminated logo")))
    handler._calculate_visual_feature_match = MagicMock(return_value=0.75)
    outcome = handler._rule_visual(
        RuleBinding(rule_id="v", kind="visual_features", target_id="zone_backlit", params={"expected": ["logo"]}), []
    )
    handler._calculate_visual_feature_match.assert_called_once()
    assert handler._calculate_visual_feature_match.call_args.args[0] == ["logo"]
    assert outcome.assessed and outcome.passed is True and outcome.score == pytest.approx(0.75)


def test_zone_present_uncertain_membership_is_unassessed(handler):
    definition = _definition()
    binding = RuleBinding(rule_id="z", kind="zone_present", target_id="zone_backlit")
    _set_context(handler, definition, _perception(_zone(membership=FixtureMembership.UNCERTAIN)))
    assert handler._rule_zone_present(binding, []).assessed is False
    _set_context(handler, definition, _perception(_zone()))
    present = handler._rule_zone_present(binding, [])
    assert present.assessed and present.passed and present.score == 1.0
    _set_context(handler, definition, _perception(None))
    absent = handler._rule_zone_present(binding, [])
    assert absent.assessed and absent.passed is False and absent.score == 0.0


async def test_rule_exception_is_isolated(handler):
    handler._check_illumination = AsyncMock(side_effect=RuntimeError("503"))
    definition = _definition()
    _set_context(handler, definition, _perception(_zone()))
    ctx = _ctx(definition)
    bindings = [
        RuleBinding(rule_id="ill", kind="illumination", target_id="zone_backlit", params={"required": "on"}),
        RuleBinding(rule_id="z", kind="zone_present", target_id="zone_backlit"),
    ]
    out = await handler._evaluate_rules(bindings, {"img0": IMAGE}, [], ctx)
    assert out["ill"].assessed is False and "503" in out["ill"].detail
    assert out["z"].assessed is True and out["z"].passed is True
    assert ctx.errors == ["rule ill: 503"]


async def test_compare_zone_only_header_shelf_penalty_once(handler):
    handler._check_illumination = AsyncMock(return_value="illumination_status: OFF")
    definition = _definition()
    bindings = [
        RuleBinding(rule_id="z", kind="zone_present", target_id="zone_backlit"),
        RuleBinding(
            rule_id="ill", kind="illumination", target_id="zone_backlit", params={"required": "on", "penalty": 0.5}
        ),
    ]
    handler._images_for_rules()["img0"] = IMAGE
    result = await handler.compare([_perception(_zone())], [_identifications()], _ctx(definition, bindings))
    header = next(s for s in result.shelf_scores if s.shelf_id == "header")
    assert header.expected_facings == 0
    assert header.lenient_score == pytest.approx(1.0 * (1 - 0.5 / 1))  # zone_score 1.0, penalty applied once
    top = next(s for s in result.shelf_scores if s.shelf_id == "top")
    assert top.facing_lenient == pytest.approx(1.0)
    statuses = {p.facing_id: p.status for p in result.position_results}
    assert statuses == {"top_f1": FacingStatus.MATCH, "top_f2": FacingStatus.MATCH}
    handler._check_illumination.assert_awaited_once()
    assert handler._images_for_rules() == {}  # cleared at the end of compare
    header_result = next(r for r in result.compliance_results if r.shelf_level == "header")
    assert header_result.compliance_status.value == "non_compliant"
    assert result.overall_compliant is False


async def test_compare_inconclusive_is_not_compliant(handler):
    definition = _definition(with_header=False)
    idents = _identifications(products=("ES-100",))
    result = await handler.compare([_perception(products=("ES-100", "ES-200"))], [idents], _ctx(definition))
    assert result.assessment_status == AssessmentStatus.INCONCLUSIVE
    assert result.overall_compliant is False


async def test_compare_complete_and_compliant(handler):
    definition = _definition(with_header=False)
    result = await handler.compare([_perception()], [_identifications()], _ctx(definition))
    assert result.assessment_status == AssessmentStatus.COMPLETE
    assert result.overall_compliant is True
    assert [r.compliance_status.value for r in result.compliance_results] == ["compliant"]


async def test_compare_ignores_off_fixture_observations(handler):
    definition = _definition(with_header=False)
    perception = _perception()
    perception.shapes[1] = perception.shapes[1].model_copy(update={"membership": FixtureMembership.OFF_FIXTURE})
    result = await handler.compare([perception], [_identifications()], _ctx(definition))
    statuses = {p.facing_id: p.status for p in result.position_results}
    assert statuses["top_f1"] == FacingStatus.MATCH
    assert statuses["top_f2"] == FacingStatus.NOT_VISIBLE


def test_handler_is_a_full_cycle_type(handler):
    assert all(handler._implements(name) for name in ("perceive", "identify", "compare"))
