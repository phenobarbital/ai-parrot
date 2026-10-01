"""FEAT-624 — fact_tag_present evaluation (spec §2 outcome table)."""

from __future__ import annotations

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.comparison.registration import ImageRegistration
from parrot_pipelines.planogram.comparison.rules import _rule_fact_tag, evaluate_rules
from parrot_pipelines.planogram.contracts import (
    CycleContext,
    FixtureMembership,
    IdentificationResult,
    OcrReading,
    PerceptionResult,
    Shape,
    ShapeKind,
    Slot,
)


def _box(x1, y1, x2, y2):
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0)


def _perception(image_id="img0", tag_text=None, with_tag=True, membership=FixtureMembership.ON_FIXTURE):
    """Two slots side by side (s1 left, s2 right); optionally one tag under s1."""
    slots = [
        Slot(slot_id=f"{image_id}:s1", image_id=image_id, row_index=0, slot_index=1, box=_box(0, 100, 100, 300)),
        Slot(slot_id=f"{image_id}:s2", image_id=image_id, row_index=0, slot_index=2, box=_box(100, 100, 200, 300)),
    ]
    shapes = []
    readings = {}
    if with_tag:
        shapes.append(
            Shape(
                shape_id=f"{image_id}:t1",
                image_id=image_id,
                kind=ShapeKind.FACT_TAG,
                box=_box(20, 290, 80, 320),
                membership=membership,
            )
        )
        if tag_text:
            readings[f"{image_id}:t1"] = OcrReading(text=tag_text)
    return PerceptionResult(
        image_id=image_id, image_size=(200, 400), shapes=shapes, slots=slots, ocr_readings=readings
    )


def _registration(image_id="img0", facing_slot="s1"):
    return ImageRegistration(image_id=image_id, assignments={f"{image_id}:{facing_slot}": "f1"})


def _binding(price_required=False):
    return RuleBinding(
        rule_id="fact_tag_present:f1",
        kind="fact_tag_present",
        target_id="f1",
        params={"price_required": price_required},
        mandatory=False,
    )


def _ids(*image_ids):
    return [IdentificationResult(image_id=image_id, identifications=[]) for image_id in image_ids]


def test_fact_tag_present_passes_with_anchored_tag():
    outcome = _rule_fact_tag(_binding(), [_perception()], _ids("img0"), [_registration()])
    assert (outcome.assessed, outcome.passed, outcome.penalty) == (True, True, 0.0)


def test_fact_tag_present_fails_when_facing_seen_without_tag():
    outcome = _rule_fact_tag(_binding(), [_perception(with_tag=False)], _ids("img0"), [_registration()])
    assert (outcome.assessed, outcome.passed, outcome.detail, outcome.penalty) == (
        True,
        False,
        "fact tag not observed",
        0.0,
    )


def test_tag_under_neighbour_is_not_credited():
    outcome = _rule_fact_tag(_binding(), [_perception()], _ids("img0"), [_registration(facing_slot="s2")])
    assert outcome.passed is False


def test_fact_tag_unassessed_when_facing_not_registered():
    outcome = _rule_fact_tag(_binding(), [_perception()], _ids("img0"), [ImageRegistration(image_id="img0")])
    assert (outcome.assessed, outcome.passed, outcome.detail) == (False, None, "facing not observed")


def test_fact_tag_price_required_needs_legible_price():
    no_price = _rule_fact_tag(_binding(True), [_perception(tag_text="ES-60W")], _ids("img0"), [_registration()])
    assert (no_price.passed, no_price.detail) == (False, "fact tag present, price not legible")
    priced = _rule_fact_tag(_binding(True), [_perception(tag_text="$129.99")], _ids("img0"), [_registration()])
    assert priced.passed is True


def test_fact_tag_seen_in_any_image_passes():
    outcome = _rule_fact_tag(
        _binding(),
        [_perception("img0", with_tag=False), _perception("img1")],
        _ids("img0", "img1"),
        [_registration("img0"), _registration("img1")],
    )
    assert outcome.passed is True


def test_fact_tag_anchor_shape_counts():
    perception = _perception(with_tag=False)
    tag_id = "img0:t1"
    perception.shapes.append(
        Shape(
            shape_id=tag_id,
            image_id="img0",
            kind=ShapeKind.FACT_TAG,
            box=_box(20, 500, 80, 530),
            membership=FixtureMembership.ON_FIXTURE,
        )
    )
    perception.slots[0].anchor_shape_id = tag_id
    outcome = _rule_fact_tag(
        _binding(),
        [perception],
        _ids("img0"),
        [ImageRegistration(image_id="img0", assignments={tag_id: "f1"})],
    )
    assert outcome.passed is True


def test_off_fixture_tag_is_ignored():
    outcome = _rule_fact_tag(
        _binding(), [_perception(membership=FixtureMembership.OFF_FIXTURE)], _ids("img0"), [_registration()]
    )
    assert outcome.passed is False


def test_evaluate_rules_dispatches_fact_tag():
    definition = load_slots_definition(
        {
            "shelves": [
                {
                    "shelf_id": "s1",
                    "shelf_number": 1,
                    "facings": [
                        {
                            "facing_id": "f1",
                            "shelf_id": "s1",
                            "slot": 1,
                            "product": "A",
                            "descriptors": {"display_name": "A"},
                        }
                    ],
                }
            ]
        }
    )
    ctx = CycleContext(definition=definition, bindings=[_binding()])
    outcome = evaluate_rules([_perception()], _ids("img0"), [_registration()], ctx)["fact_tag_present:f1"]
    assert outcome.passed is True and outcome.detail != "unknown rule kind"
