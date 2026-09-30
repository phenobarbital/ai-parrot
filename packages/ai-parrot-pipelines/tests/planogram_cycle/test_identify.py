"""Offline tests for stage-2 identification strategies (FEAT-574, Module 12)."""

import asyncio
import math

import numpy as np
import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import (
    AddedShape,
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FixtureMembership,
    Identification,
    IdentificationResponse,
    ObservationSource,
    OcrReading,
    PerceptionResult,
    ReferenceImage,
    Shape,
    ShapeKind,
    Slot,
)
from parrot_pipelines.planogram.identification.identify import (
    IDENTIFY_PROMPT_VERSION,
    build_identify_prompt,
    identify_full_image,
    identify_slots,
    identify_strips,
    validate_response,
)
from parrot_pipelines.planogram.identification.vision import VisionError
from parrot_pipelines.planogram.layout import LayoutProfile, ReferencePolicy
from parrot_pipelines.planogram.perception.profiles import PRICE_TAG_PROFILE
from parrot_pipelines.planogram.perception.slots import strip_box

W, H = 600, 300


class InlineExecutor:
    async def run(self, fn, *args):
        return fn(*args)


class StubAdapter:
    """Pops queued answers; an Exception instance is raised. Callables receive the prompt."""

    def __init__(self, *answers):
        self.answers, self.calls, self.images = list(answers), [], []

    async def ask(self, prompt, images, schema, *, stage, prompt_version, system_prompt=None):
        self.calls.append(prompt)
        self.images.append(list(images))
        assert images and images[0][:8] == b"\x89PNG\r\n\x1a\n"
        assert prompt_version == IDENTIFY_PROMPT_VERSION
        item = self.answers.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item(prompt) if callable(item) else item


def _ctx(adapter) -> CycleContext:
    return CycleContext(
        vision=adapter,
        executor=InlineExecutor(),
        ocr=None,
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
    )


def _layout(**overrides) -> LayoutProfile:
    return LayoutProfile(shape_profiles=[PRICE_TAG_PROFILE], **overrides)


def _box(x1, y1, x2, y2, conf=1.0):
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=conf)


@pytest.fixture
def perception() -> PerceptionResult:
    """600x300 image, 2 rows x 3 slots with ocr_text on the anchor shapes."""
    shapes, slots = [], []
    for row in range(2):
        for idx in range(1, 4):
            x1 = 20 + (idx - 1) * 190
            y1 = 20 + row * 140
            tag_id = f"img0:tag:r{row}s{idx}"
            shapes.append(
                Shape(
                    shape_id=tag_id,
                    image_id="img0",
                    kind=ShapeKind.PRICE_TAG,
                    box=_box(x1 + 40, y1 + 100, x1 + 120, y1 + 120),
                    row_index=row,
                    slot_index=idx,
                    ocr_text=f"OCR-{row}{idx}",
                    membership=FixtureMembership.ON_FIXTURE,
                )
            )
            slots.append(
                Slot(
                    slot_id=f"img0:r{row}:s{idx}",
                    image_id="img0",
                    row_index=row,
                    slot_index=idx,
                    box=_box(x1, y1, x1 + 170, y1 + 95),
                    anchor_shape_id=tag_id,
                )
            )
    zone = Shape(shape_id="img0:zone", image_id="img0", kind=ShapeKind.ZONE, box=_box(10, 0, 590, 15))
    return PerceptionResult(image_id="img0", image_size=(W, H), shapes=shapes, slots=slots, zones=[zone], row_count=2)


def _image():
    return np.full((H, W, 3), 120, np.uint8)


def _answer(ids, product="ES-400"):
    return IdentificationResponse(
        existing_identifications=[
            Identification(shape_id=i, product=product, raw_confidence=0.8, evidence=["read"]) for i in ids
        ]
    )


def _counter():
    state = {"n": 0}

    def allocate():
        state["n"] += 1
        return f"img0:added:{state['n']}"

    return allocate


def test_added_shapes_validation(perception):
    """5 rejections (non-finite, out of bounds, zero area, outside strip, duplicate) + 1 accepted."""
    added = [
        AddedShape(box_norm=[0, 0, 0, 0], raw_confidence=0.4),  # zero area
        AddedShape.model_construct(box_norm=[0, 0, math.nan, 10], raw_confidence=0.4),  # non-finite
        AddedShape(box_norm=[0, 0, 1200, 500], raw_confidence=0.4),  # out of bounds
        AddedShape(box_norm=[-50, 0, 100, 100], raw_confidence=0.4),  # outside the strip
        AddedShape(box_norm=[67, 33, 383, 317], raw_confidence=0.4),  # duplicates slot r0:s1
        AddedShape(box_norm=[600, 850, 900, 990], product="NEW-1", raw_confidence=0.37, evidence=["seen"]),
    ]
    response = IdentificationResponse(existing_identifications=[], added_shapes=added)
    idents, shapes, errors = validate_response(response, perception, strip=None, next_shape_id=_counter())
    assert len(errors) == 5
    assert len(shapes) == 1
    accepted = shapes[0]
    assert accepted.shape_id == "img0:added:1" and accepted.source == ObservationSource.LLM_ADDED
    added_ident = next(i for i in idents if i.shape_id == "img0:added:1")
    assert added_ident.raw_confidence == pytest.approx(0.37)
    assert added_ident.source == ObservationSource.LLM_ADDED
    assert len([i for i in idents if i.uncertain]) == 6  # every known slot was missing in the response


def test_added_shape_coordinates_are_source_pixels(perception):
    """Box_norm relative to a strip maps back to source-image pixels (strip offset added)."""
    row1 = [s for s in perception.slots if s.row_index == 1]
    strip = strip_box(row1, perception.image_size)
    response = IdentificationResponse(added_shapes=[AddedShape(box_norm=[0, 900, 500, 1000], raw_confidence=0.5)])
    _, shapes, errors = validate_response(response, perception, strip=strip, next_shape_id=_counter())
    assert errors == []
    box = shapes[0].box
    assert box.y1 == strip.y1 and box.x2 == strip.x2
    assert box.x1 == strip.x1 + round(0.9 * (strip.x2 - strip.x1))


def test_unknown_and_missing_existing_ids(perception):
    """Unknown id ⇒ error + dropped; missing known id ⇒ uncertain; duplicate ⇒ first wins."""
    response = IdentificationResponse(
        existing_identifications=[
            Identification(shape_id="img0:r0:s1", product="FIRST", evidence=["a"], raw_confidence=0.7),
            Identification(shape_id="img0:r0:s1", product="SECOND", evidence=["b"]),
            Identification(shape_id="ghost", product="X", evidence=["c"]),
        ]
    )
    idents, _, errors = validate_response(response, perception, strip=None, next_shape_id=_counter())
    by_id = {i.shape_id: i for i in idents}
    assert "ghost" not in by_id and any("unknown id ghost" in e for e in errors)
    assert by_id["img0:r0:s1"].product == "FIRST" and by_id["img0:r0:s1"].raw_confidence == pytest.approx(0.7)
    assert by_id["img0:r0:s1"].image_id == "img0" and by_id["img0:r0:s1"].source == ObservationSource.CV
    missing = by_id["img0:r1:s3"]
    assert missing.uncertain and missing.raw_confidence == 0.0 and missing.evidence == ["missing_in_response"]


def test_identity_fields_resolve_defaulted_occupancy_without_using_evidence(perception):
    """Structured identity proves presence; prose alone cannot turn an unknown slot into occupied."""
    response = IdentificationResponse(
        existing_identifications=[
            Identification(shape_id="img0:r0:s1", brand="HP", evidence=["package visible"]),
            Identification(shape_id="img0:r0:s2", product="null", text="Empty Slot", evidence=["package visible"]),
            Identification(shape_id="img0:r0:s3", evidence=["HP 62XL package visible"]),
        ]
    )
    idents, _, _ = validate_response(response, perception, strip=None, next_shape_id=_counter())
    by_id = {item.shape_id: item for item in idents}
    assert by_id["img0:r0:s1"].occupancy == "occupied"
    assert by_id["img0:r0:s2"].occupancy == "unknown"
    assert by_id["img0:r0:s3"].occupancy == "unknown"


async def test_failed_strip_is_isolated(perception):
    row0 = [s.slot_id for s in perception.slots if s.row_index == 0]
    adapter = StubAdapter(_answer(row0), VisionError("boom"))
    ctx = _ctx(adapter)
    result = await identify_strips(_image(), perception, ctx, vocabulary=["family"])
    assert len(adapter.calls) == 2
    by_id = {i.shape_id: i for i in result.identifications}
    assert all(not by_id[i].uncertain and by_id[i].product == "ES-400" for i in row0)
    row1 = [s.slot_id for s in perception.slots if s.row_index == 1]
    assert all(by_id[i].uncertain and by_id[i].evidence[0].startswith("identify_failed") for i in row1)
    assert len(result.errors) == 1 and "boom" in result.errors[0]
    assert ctx.errors == result.errors
    assert [i.shape_id for i in result.identifications] == row0 + row1


async def test_full_image_makes_one_call(perception):
    ids = [s.slot_id for s in perception.slots]
    adapter = StubAdapter(_answer(ids))
    result = await identify_full_image(_image(), perception, _ctx(adapter), vocabulary=[])
    assert len(adapter.calls) == 1
    assert len(result.identifications) == 6 and not any(i.uncertain for i in result.identifications)


async def test_incomplete_response_is_retried_once(perception):
    ids = [slot.slot_id for slot in perception.slots]
    adapter = StubAdapter(_answer(ids[:-1]), _answer(ids))
    result = await identify_full_image(_image(), perception, _ctx(adapter), vocabulary=[])
    assert len(adapter.calls) == 2
    assert "CORRECTION" in adapter.calls[1]
    assert ids[-1] in adapter.calls[1]
    assert len(result.identifications) == 6 and not any(item.uncertain for item in result.identifications)


async def test_strips_split_large_rows():
    """20 targets in one row → 3 calls (7/7/6)."""
    slots = [
        Slot(slot_id=f"img0:r0:s{i}", image_id="img0", row_index=0, slot_index=i, box=_box(i * 50, 10, i * 50 + 40, 90))
        for i in range(1, 21)
    ]
    perception = PerceptionResult(image_id="img0", image_size=(1100, 120), slots=slots, row_count=1)
    seen = []

    def answer(prompt):
        ids = [s.slot_id for s in slots if f'"{s.slot_id}"' in prompt]
        seen.append(len(ids))
        return _answer(ids)

    adapter = StubAdapter(answer, answer, answer)
    result = await identify_strips(np.zeros((120, 1100, 3), np.uint8), perception, _ctx(adapter), vocabulary=[])
    assert len(adapter.calls) == 3
    assert seen == [7, 7, 6]
    assert len(result.identifications) == 20 and not any(i.uncertain for i in result.identifications)


def test_prompt_has_ocr_text_and_vocabulary_not_products(perception):
    areas = [{"id": "img0:r0:s1", "mark": 1, "box_2d": [0, 0, 500, 500], "ocr_text": "OCR-01"}]
    prompt = build_identify_prompt(areas, ["family", "colors"])
    assert "OCR-01" in prompt and "family, colors" in prompt
    assert "planogram" not in prompt.lower()
    assert "expected" not in prompt.lower()


async def test_prompt_built_by_strategy_carries_stage1_ocr(perception):
    row0 = [s.slot_id for s in perception.slots if s.row_index == 0]
    row1 = [s.slot_id for s in perception.slots if s.row_index == 1]
    adapter = StubAdapter(_answer(row0), _answer(row1))
    await identify_strips(_image(), perception, _ctx(adapter), vocabulary=["family"])
    assert "OCR-01" in adapter.calls[0] and "OCR-03" in adapter.calls[0]
    assert "OCR-13" in adapter.calls[1] and "OCR-13" not in adapter.calls[0]


async def test_unknown_vocabulary_raises(perception):
    with pytest.raises(ValueError):
        await identify_full_image(_image(), perception, _ctx(StubAdapter()), vocabulary=["sku_color"])


async def test_additions_get_membership(perception):
    ids = [s.slot_id for s in perception.slots]
    response = _answer(ids)
    response.added_shapes = [AddedShape(box_norm=[600, 850, 900, 990], product="NEW-1", raw_confidence=0.6)]
    result = await identify_full_image(_image(), perception, _ctx(StubAdapter(response)), vocabulary=[])
    assert len(result.added) == 1
    added = result.added[0]
    assert added.membership == FixtureMembership.ON_FIXTURE  # inside the zone's anchor column
    assert added.membership_evidence
    assert result.identifications[-1].shape_id == added.shape_id


def test_prompt_version_is_v2():
    assert IDENTIFY_PROMPT_VERSION == "identify-v2-ocr"


def test_v2_prompt_has_occupancy_and_printed_code_rules_without_expectations():
    prompt = build_identify_prompt([], ["family"])
    assert "empty" in prompt and "ocr_text is NOT evidence of emptiness" in prompt
    assert "printed product code" in prompt
    assert "planogram" not in prompt.lower() and "expected" not in prompt.lower()


def test_reference_labels_listed_without_catalogue_keys():
    prompt = build_identify_prompt([], [], reference_labels=["ref-0001", "ref-0002"])
    assert "ref-0001" in prompt and "ref-0002" in prompt and "reference_id" in prompt
    assert "catalog_key" not in prompt


async def test_references_attached_to_initial_and_repair_calls(perception):
    ids = [slot.slot_id for slot in perception.slots]
    adapter = StubAdapter(_answer(ids[:-1]), _answer(ids))
    ctx = _ctx(adapter)
    ctx.layout = _layout()
    ctx.reference_bank = [ReferenceImage(label="ref-0001", image=b"reference", catalog_key="A")]
    await identify_full_image(_image(), perception, ctx, vocabulary=[])
    assert adapter.images[0] == adapter.images[1]
    assert len(adapter.images[0]) == 2


async def test_unknown_reference_id_is_rejected(perception):
    ids = [slot.slot_id for slot in perception.slots]
    answer = _answer(ids)
    answer.existing_identifications[0].reference_id = "ref-9999"
    result = await identify_full_image(_image(), perception, _ctx(StubAdapter(answer)), vocabulary=[])
    identification = result.identifications[0]
    assert identification.reference_id is None
    assert identification.product == "ES-400" and identification.raw_confidence == pytest.approx(0.8)
    assert any("unknown reference_id ref-9999" in error for error in result.errors)


async def test_capped_references_reported(perception):
    ids = [slot.slot_id for slot in perception.slots]
    ctx = _ctx(StubAdapter(_answer([*ids, "img0:zone"])))
    ctx.layout = _layout(references=ReferencePolicy(max_per_call=2))
    ctx.reference_bank = [ReferenceImage(label=f"ref-{index}", image=b"reference", catalog_key=str(index)) for index in range(7)]
    result = await identify_full_image(_image(), perception, ctx, vocabulary=[])
    assert len(ctx.vision.images[0]) == 3
    assert any("references: omitted" in error for error in result.errors)


async def test_zones_are_targets_only_with_layout(perception):
    ids = [slot.slot_id for slot in perception.slots]
    without_layout = await identify_full_image(_image(), perception, _ctx(StubAdapter(_answer(ids))), vocabulary=[])
    ctx = _ctx(StubAdapter(_answer([*ids, "img0:zone"])))
    ctx.layout = _layout()
    with_layout = await identify_full_image(_image(), perception, ctx, vocabulary=[])
    assert len(without_layout.identifications) == 6
    assert [item.shape_id for item in with_layout.identifications][-1] == "img0:zone"


async def test_own_box_ocr_used_and_tag_text_separate(perception):
    ids = [slot.slot_id for slot in perception.slots]
    perception.ocr_readings = {"img0:r0:s1": OcrReading(text="62XL", confidence=0.9)}
    adapter = StubAdapter(_answer(ids))
    await identify_full_image(_image(), perception, _ctx(adapter), vocabulary=[])
    assert '"ocr_text":"62XL"' in adapter.calls[0]
    assert '"tag_text":"OCR-01"' in adapter.calls[0]
    assert '"ocr_text":null' in adapter.calls[0]


async def test_custom_descriptor_allowed_when_declared_by_profile(perception):
    ids = [slot.slot_id for slot in perception.slots]
    with pytest.raises(ValueError):
        await identify_full_image(_image(), perception, _ctx(StubAdapter()), vocabulary=["capacity_ml"])
    ctx = _ctx(StubAdapter(_answer([*ids, "img0:zone"])))
    ctx.layout = _layout(descriptor_fields=["capacity_ml"])
    result = await identify_full_image(_image(), perception, ctx, vocabulary=["capacity_ml"])
    assert len(result.identifications) == 7


async def test_identify_slots_one_call_per_target(perception):
    ids = [slot.slot_id for slot in perception.slots]
    adapter = StubAdapter(*(_answer([identifier]) for identifier in ids))
    await identify_slots(_image(), perception, _ctx(adapter), vocabulary=[])
    assert len(adapter.calls) == 6
    assert all(sum(f'"{identifier}"' in prompt for identifier in ids) == 1 for prompt in adapter.calls)


async def test_identify_slots_addition_is_source_pixels(perception):
    slot = perception.slots[0]
    response = _answer([slot.slot_id])
    response.added_shapes = [AddedShape(box_norm=[800, 800, 950, 950], raw_confidence=0.5)]
    answers = [response, *(_answer([other.slot_id]) for other in perception.slots[1:])]
    result = await identify_slots(_image(), perception, _ctx(StubAdapter(*answers)), vocabulary=[])
    added = result.added[0].box
    crop = strip_box([slot], perception.image_size, pad=0.08)
    assert crop.x1 <= added.x1 < added.x2 <= crop.x2 and crop.y1 <= added.y1 < added.y2 <= crop.y2


async def test_identify_slots_failure_isolated(perception):
    ids = [slot.slot_id for slot in perception.slots]
    adapter = StubAdapter(_answer([ids[0]]), VisionError("boom"), *(_answer([identifier]) for identifier in ids[2:]))
    result = await identify_slots(_image(), perception, _ctx(adapter), vocabulary=[])
    by_id = {item.shape_id: item for item in result.identifications}
    assert by_id[ids[1]].uncertain
    assert all(not by_id[identifier].uncertain for identifier in ids if identifier != ids[1])
    assert len(result.errors) == 1 and "boom" in result.errors[0]


async def test_cancellation_propagates(perception):
    with pytest.raises(asyncio.CancelledError):
        await identify_slots(_image(), perception, _ctx(StubAdapter(asyncio.CancelledError())), vocabulary=[])
