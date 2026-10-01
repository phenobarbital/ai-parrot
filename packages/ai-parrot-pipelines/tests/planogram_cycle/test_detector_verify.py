"""Offline tests for the LLM detector fallback and closed-set verification (FEAT-574, Module 12)."""

import numpy as np
import pytest

from parrot.models.detections import BoundingBox, Detection, Detections, DetectionBox
from parrot_pipelines.planogram.comparison.definition import load_slots_definition
from parrot_pipelines.planogram.contracts import (
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FixtureMembership,
    Identification,
    ObservationSource,
    ShapeKind,
)
from parrot_pipelines.planogram.identification.detector import GENERIC_DETECTION_PROMPT, llm_detect_shapes
from parrot_pipelines.planogram.identification.verify import (
    CHOICE_CANNOT_TELL,
    CHOICE_OTHER,
    VerificationAnswer,
    option_order,
    pick_candidates,
    verify_unresolved,
)
from parrot_pipelines.planogram.identification.vision import VisionError


class InlineExecutor:
    async def run(self, fn, *args):
        return fn(*args)


class StubAdapter:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    async def ask(self, prompt, images, schema, *, stage, prompt_version, system_prompt=None):
        self.calls.append((stage, prompt))
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _ctx(adapter) -> CycleContext:
    return CycleContext(
        vision=adapter,
        executor=InlineExecutor(),
        ocr=None,
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
    )


def _det(x1, y1, x2, y2, label="product", content=None, confidence=0.8):
    return Detection(label=label, confidence=confidence, content=content, bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2))


def _definition():
    """One shelf: two described Acme scanners with identifiers, one Other-brand product, one undescribed Acme."""
    return load_slots_definition(
        {
            "shelves": [
                {
                    "shelf_id": "shelf_1",
                    "shelf_number": 1,
                    "facings": [
                        {
                            "facing_id": "f1",
                            "shelf_id": "shelf_1",
                            "slot": 1,
                            "product": "ES-400",
                            "brand": "Acme",
                            "descriptors": {
                                "display_name": "Acme ES-400 Scanner",
                                "family": "ES",
                                "identifiers": ["ES-400"],
                            },
                        },
                        {
                            "facing_id": "f2",
                            "shelf_id": "shelf_1",
                            "slot": 2,
                            "product": "ES-500",
                            "brand": "Acme",
                            "descriptors": {
                                "display_name": "Acme ES-500 Scanner",
                                "family": "ES",
                                "identifiers": ["ES-500"],
                            },
                        },
                        {
                            "facing_id": "f3",
                            "shelf_id": "shelf_1",
                            "slot": 3,
                            "product": "ZZ-1",
                            "brand": "Other",
                            "descriptors": {"display_name": "Other ZZ-1"},
                        },
                        {
                            "facing_id": "f4",
                            "shelf_id": "shelf_1",
                            "slot": 4,
                            "product": "RR-60",
                            "brand": "Acme",
                            "descriptors": {"family": "RR"},
                        },
                    ],
                }
            ]
        }
    )


def _unresolved(shape_id="s1", brand="Acme", **descriptors):
    return Identification(
        shape_id=shape_id, image_id="img0", product=None, brand=brand, descriptors=descriptors, uncertain=True
    )


BOX = DetectionBox(x1=10, y1=10, x2=60, y2=60, confidence=1.0)
IMAGE = np.full((100, 100, 3), 200, np.uint8)


# --------------------------------------------------------------------------- detector


async def test_detector_maps_to_source_pixels_and_sets_source_llm():
    """4000x3000 image (downscaled for the call) → boxes in 4000x3000 space, source llm."""
    image = np.zeros((3000, 4000, 3), np.uint8)
    adapter = StubAdapter(Detections(detections=[_det(0.1, 0.2, 0.3, 0.4, content="ES-400")]))
    shapes = await llm_detect_shapes(image, "img0", _ctx(adapter), prompt=GENERIC_DETECTION_PROMPT)
    assert len(shapes) == 1
    shape = shapes[0]
    assert (shape.box.x1, shape.box.y1, shape.box.x2, shape.box.y2) == (400, 600, 1200, 1200)
    assert shape.source == ObservationSource.LLM and shape.profile == "llm_detector"
    assert shape.shape_id == "img0:llm:1" and shape.ocr_text == "ES-400" and shape.kind == ShapeKind.PRODUCT


async def test_detector_drops_degenerate_boxes():
    adapter = StubAdapter(Detections(detections=[_det(0.5, 0.5, 0.5, 0.6), _det(0.1, 0.1, 0.2, 0.2, label="banana")]))
    shapes = await llm_detect_shapes(IMAGE, "img0", _ctx(adapter), prompt="p")
    assert [s.shape_id for s in shapes] == ["img0:llm:1"]
    assert shapes[0].kind == ShapeKind.UNKNOWN


async def test_detector_failure_returns_empty_and_records_error():
    ctx = _ctx(StubAdapter(VisionError("x")))
    assert await llm_detect_shapes(IMAGE, "img0", ctx, prompt="p") == []
    assert ctx.errors == ["llm_detector img0: x"]


async def test_detector_applies_membership():
    detections = [
        _det(0.3, 0.0, 0.7, 0.1, label="zone"),
        _det(0.35, 0.3, 0.45, 0.5),
        _det(0.0, 0.3, 0.05, 0.5),
    ]
    shapes = await llm_detect_shapes(
        np.zeros((1000, 1000, 3), np.uint8), "img0", _ctx(StubAdapter(Detections(detections=detections))), prompt="p"
    )
    assert shapes[0].kind == ShapeKind.ZONE
    by_id = {s.shape_id: s for s in shapes}
    assert by_id["img0:llm:2"].membership == FixtureMembership.ON_FIXTURE
    assert by_id["img0:llm:3"].membership == FixtureMembership.OFF_FIXTURE


# --------------------------------------------------------------------------- verification


def test_pick_candidates_requires_partial_read():
    definition = _definition()
    assert pick_candidates(_unresolved(brand=None), definition, 3) == []
    acme = pick_candidates(_unresolved(), definition, 3)
    assert [c.product for c in acme] == ["ES-400", "ES-500", "RR-60"]  # described first, then undescribed
    es_only = pick_candidates(_unresolved(family="ES"), definition, 3)
    assert [c.product for c in es_only] == ["ES-400", "ES-500"]  # RR family contradicts
    assert len(pick_candidates(_unresolved(), definition, 1)) == 2


def test_option_order_is_deterministic():
    products = ["ES-400", "ES-500", "RR-60", "ZZ-1"]
    first = option_order("img0:a", products)
    assert first == option_order("img0:a", list(reversed(products)))
    assert sorted(first) == sorted(products)
    orders = {tuple(option_order(f"img0:{i}", products)) for i in range(12)}
    assert len(orders) > 1


async def test_offered_sku_without_visible_text_is_not_evidence():
    answer = VerificationAnswer(choice="ES-400", visible_text=[], evidence="it is the ES-400", confidence=0.9)
    adapter = StubAdapter(answer)
    original = [_unresolved()]
    result = await verify_unresolved(IMAGE, original, _definition(), _ctx(adapter), boxes={"s1": BOX})
    assert len(adapter.calls) == 1
    assert result[0] is original[0] and result[0].uncertain


async def test_shared_token_does_not_discriminate():
    """'Acme' and 'Scanner' are shared by the offered ES options; they do not prove ES-400."""
    answer = VerificationAnswer(choice="ES-400", visible_text=["ACME Scanner"], confidence=0.9)
    result = await verify_unresolved(
        IMAGE, [_unresolved(family="ES")], _definition(), _ctx(StubAdapter(answer)), boxes={"s1": BOX}
    )
    assert result[0].uncertain


async def test_verification_accepts_cited_identifier():
    answer = VerificationAnswer(choice="ES-400", visible_text=["ES-400 duplex"], evidence="model code", confidence=0.7)
    original = _unresolved()
    result = await verify_unresolved(IMAGE, [original], _definition(), _ctx(StubAdapter(answer)), boxes={"s1": BOX})
    verified = result[0]
    assert verified.product == "ES-400" and verified.uncertain is False
    assert verified.evidence[-1] == "verify: model code"
    assert verified.raw_confidence == pytest.approx(0.7)
    assert verified.source == original.source
    assert original.uncertain and original.product is None  # input not mutated


@pytest.mark.parametrize("choice", [CHOICE_OTHER, CHOICE_CANNOT_TELL, "NOT-OFFERED"])
async def test_other_and_cannot_tell_leave_unresolved(choice):
    answer = VerificationAnswer(choice=choice, visible_text=["ES-400"], confidence=0.9)
    result = await verify_unresolved(
        IMAGE, [_unresolved()], _definition(), _ctx(StubAdapter(answer)), boxes={"s1": BOX}
    )
    assert result[0].uncertain and result[0].product is None


async def test_missing_box_is_skipped_without_call():
    adapter = StubAdapter()
    idents = [_unresolved(), _unresolved("s2", brand=None)]
    result = await verify_unresolved(IMAGE, idents, _definition(), _ctx(adapter), boxes={"s2": BOX})
    assert adapter.calls == []  # s1 has no box, s2 has no partial read
    assert result == idents and result is not idents


async def test_failed_verification_call_is_isolated():
    ok = VerificationAnswer(choice="ES-500", visible_text=["ES-500"], confidence=0.6)
    ctx = _ctx(StubAdapter(VisionError("503"), ok))
    resolved = Identification(shape_id="s0", image_id="img0", product="ZZ-1", evidence=["read"])
    idents = [_unresolved("s1"), resolved, _unresolved("s2")]
    result = await verify_unresolved(IMAGE, idents, _definition(), ctx, boxes={"s1": BOX, "s2": BOX, "s0": BOX})
    assert result[0].uncertain
    assert result[1] is resolved
    assert result[2].product == "ES-500"
    assert ctx.errors == ["verify s1: 503"]


# ── fixture ROI before detection ──────────────────────────────────────────────


def _roi_ctx(adapter) -> CycleContext:
    return _ctx(adapter).model_copy(update={"roi_prompt": "find the endcap"})


async def test_detection_runs_on_the_fixture_crop_and_returns_source_pixels():
    from parrot_pipelines.planogram.identification.detector import ROI_STAGE

    image = np.zeros((1000, 2000, 3), dtype=np.uint8)
    roi = Detections(detections=[_det(0.25, 0.1, 0.75, 0.9, label="endcap", confidence=0.9)])
    inside = Detections(detections=[_det(0.5, 0.5, 1.0, 1.0)])
    adapter = StubAdapter(roi, inside)

    shapes = await llm_detect_shapes(image, "img0", _roi_ctx(adapter), prompt=GENERIC_DETECTION_PROMPT)

    assert [stage for stage, _ in adapter.calls] == [ROI_STAGE, "detect"]
    assert adapter.calls[0][1] == "find the endcap"
    # fixture 500..1500 x 100..900 padded 4% -> 460..1540 x 68..932; the lower-right quarter of that crop
    box = shapes[0].box
    assert (box.x1, box.y1, box.x2, box.y2) == (1000, 500, 1540, 932)


async def test_roi_panel_becomes_the_zone_the_detector_missed():
    image = np.zeros((1000, 2000, 3), dtype=np.uint8)
    roi = Detections(
        detections=[
            _det(0.25, 0.3, 0.75, 0.9, label="endcap"),
            _det(0.3, 0.1, 0.7, 0.3, label="poster_panel"),
            _det(0.3, 0.1, 0.4, 0.15, label="brand_logo", content="ACME"),
        ]
    )
    adapter = StubAdapter(roi, Detections(detections=[_det(0.1, 0.5, 0.4, 0.8)]))

    shapes = await llm_detect_shapes(image, "img0", _roi_ctx(adapter), prompt="p")

    zone = shapes[0]
    assert zone.kind == ShapeKind.ZONE and zone.shape_id == "img0:roi:panel" and zone.ocr_text == "ACME"
    assert (zone.box.x1, zone.box.y1, zone.box.x2, zone.box.y2) == (600, 100, 1400, 300)
    # The fixture box was stretched up to the panel, so product coordinates start at its top.
    assert shapes[1].box.y1 > 300


@pytest.mark.parametrize(
    "answer",
    [
        VisionError("boom"),
        Detections(detections=[]),
        Detections(detections=[_det(0.4, 0.4, 0.45, 0.45, label="endcap")]),
    ],
)
async def test_without_a_usable_roi_the_whole_image_is_detected(answer):
    image = np.zeros((1000, 2000, 3), dtype=np.uint8)
    adapter = StubAdapter(answer, Detections(detections=[_det(0.0, 0.0, 0.5, 0.5)]))
    ctx = _roi_ctx(adapter)

    shapes = await llm_detect_shapes(image, "img0", ctx, prompt="p")

    assert (shapes[0].box.x2, shapes[0].box.y2) == (1000, 500)
    assert any(error.startswith("roi img0") for error in ctx.errors)


def test_render_roi_prompt_fills_placeholders_and_survives_stray_braces():
    from parrot_pipelines.planogram.identification.detector import render_roi_prompt

    assert render_roi_prompt(None) is None and render_roi_prompt("  ") is None
    rendered = render_roi_prompt("{brand}: {tag_hint} {image_size}", brand="Acme", tags=["b", "a", "a"])
    assert rendered.startswith("Acme: 'a', 'b'\n\n") and "box_2d" in rendered
    assert render_roi_prompt('return {"detections": []}').startswith('return {"detections": []}\n')


async def test_roi_fixture_is_stretched_to_hold_its_components():
    """A fixture box whose top edge is mislocated still includes the logo the same call located."""
    image = np.zeros((1000, 2000, 3), dtype=np.uint8)
    roi = Detections(
        detections=[
            _det(0.25, 0.65, 0.75, 0.95, label="endcap"),
            _det(0.3, 0.65, 0.7, 0.45, label="poster_panel"),
            _det(0.3, 0.1, 0.4, 0.15, label="brand_logo", content="ACME"),
        ]
    )
    adapter = StubAdapter(roi, Detections(detections=[_det(0.0, 0.0, 1.0, 1.0)]))

    shapes = await llm_detect_shapes(image, "img0", _roi_ctx(adapter), prompt="p")

    box = shapes[0].box
    assert box.y1 < 100 and box.y2 > 950 and shapes[0].shape_id != "img0:roi:panel"


async def test_a_small_zone_on_the_roi_panel_is_a_card():
    image = np.zeros((1000, 2000, 3), dtype=np.uint8)
    roi = Detections(
        detections=[_det(0.0, 0.0, 1.0, 1.0, label="endcap"), _det(0.2, 0.0, 0.8, 0.4, label="poster_panel")]
    )
    found = Detections(
        detections=[_det(0.2, 0.0, 0.8, 0.4, label="zone"), _det(0.3, 0.3, 0.4, 0.45, label="zone", content="SAVE")]
    )
    adapter = StubAdapter(roi, found)

    shapes = await llm_detect_shapes(image, "img0", _roi_ctx(adapter), prompt="p")

    assert [shape.kind for shape in shapes] == [ShapeKind.ZONE, ShapeKind.FACT_TAG]


async def test_a_small_zone_on_the_largest_zone_is_a_card_without_roi():
    image = np.zeros((1000, 2000, 3), dtype=np.uint8)
    found = Detections(detections=[_det(0.3, 0.3, 0.4, 0.45, label="zone"), _det(0.2, 0.0, 0.8, 0.4, label="zone")])
    shapes = await llm_detect_shapes(image, "img0", _ctx(StubAdapter(found)), prompt="p")
    assert sorted(shape.kind.value for shape in shapes) == ["fact_tag", "zone"]


def test_detector_schema_uses_box_2d_and_requires_a_kind():
    from pydantic import ValidationError

    from parrot_pipelines.planogram.identification.detector import KindDetections, RoiDetections

    answer = KindDetections.model_validate(
        {"detections": [{"label": "box", "confidence": 0.9, "box_2d": [100, 250, 500, 750]}]}
    )
    assert answer.detections[0].pixel_box(2000, 1000) == (500, 100, 1500, 500)
    unit = RoiDetections.model_validate(
        {"detections": [{"label": "endcap", "confidence": 1, "box_2d": [0.1, 0.25, 0.5, 0.75]}]}
    )
    assert unit.detections[0].pixel_box(2000, 1000) == (500, 100, 1500, 500)
    with pytest.raises(ValidationError):
        KindDetections.model_validate({"detections": [{"confidence": 0.9, "box_2d": [1, 2, 3, 4]}]})
    with pytest.raises(ValidationError):
        KindDetections.model_validate({"detections": [{"label": "printer", "confidence": 0.9, "box_2d": [1, 2, 3, 4]}]})


async def test_detector_reads_box_2d_answers_into_source_pixels():
    from parrot_pipelines.planogram.identification.detector import KindDetections

    image = np.zeros((1000, 2000, 3), dtype=np.uint8)
    answer = KindDetections.model_validate(
        {"detections": [{"label": "product", "confidence": 0.9, "box_2d": [100, 250, 500, 750], "content": "X"}]}
    )
    shapes = await llm_detect_shapes(image, "img0", _ctx(StubAdapter(answer)), prompt="p")
    box = shapes[0].box
    assert (box.x1, box.y1, box.x2, box.y2) == (500, 100, 1500, 500) and shapes[0].kind == ShapeKind.PRODUCT


async def test_named_roi_zones_are_observed_zones_without_a_fixture_box():
    from parrot_pipelines.planogram.identification.detector import RoiDetections

    class Layout:
        roi_zone_labels = ["top_zone", "bottom_zone", "missing_zone"]

    image = np.zeros((1000, 2000, 3), dtype=np.uint8)
    roi = RoiDetections.model_validate(
        {
            "detections": [
                {
                    "label": "top_zone",
                    "confidence": 0.9,
                    "box_2d": [200, 300, 400, 700],
                    "content": "Hello. Light: OFF",
                },
                {"label": "middle_zone", "confidence": 0.9, "box_2d": [400, 300, 700, 700], "content": "Table"},
                {"label": "bottom_zone", "confidence": 0.9, "box_2d": [600, 300, 900, 700]},
            ]
        }
    )
    adapter = StubAdapter(roi, Detections(detections=[_det(0.3, 0.0, 0.7, 0.2, label="zone", content="SIGN")]))
    ctx = _roi_ctx(adapter).model_copy(update={"layout": Layout()})

    shapes = await llm_detect_shapes(image, "img0", ctx, prompt="p")

    assert [shape.shape_id for shape in shapes[:2]] == ["img0:roi:top_zone", "img0:roi:bottom_zone"]
    top = shapes[0]
    assert top.kind == ShapeKind.ZONE and top.ocr_text == "Hello. Light: OFF"
    assert (top.box.x1, top.box.y1, top.box.x2, top.box.y2) == (600, 200, 1400, 400)
    # No fixture label: the detector saw the whole image, and nothing is reported as an error.
    assert (shapes[2].box.x1, shapes[2].box.x2) == (600, 1400) and not ctx.errors


async def test_roi_fixture_running_past_its_components_is_cut_back_sideways():
    """A fixture box that swallowed the neighbouring bay is narrowed to its own components plus a margin."""
    image = np.zeros((1000, 2000, 3), dtype=np.uint8)
    roi = Detections(
        detections=[
            _det(0.2, 0.1, 1.0, 0.9, label="endcap_roi"),
            _det(0.25, 0.1, 0.7, 0.4, label="poster_panel"),
            _det(0.25, 0.5, 0.75, 0.8, label="demo_unit"),
        ]
    )
    adapter = StubAdapter(roi, Detections(detections=[_det(0.0, 0.0, 1.0, 1.0, label="zone")]))

    shapes = await llm_detect_shapes(image, "img0", _roi_ctx(adapter), prompt="p")

    # components span x 500..1500; the right edge (2000) is cut to 1500 + 12% of 1000, then padded 4%.
    box = shapes[0].box
    assert 1620 <= box.x2 <= 1680 and box.x1 < 420
