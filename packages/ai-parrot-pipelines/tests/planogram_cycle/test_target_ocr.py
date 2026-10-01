"""Tests for own-box OCR target extraction."""

import numpy as np
import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import (
    CycleContext,
    FixtureMembership,
    PerceptionResult,
    Shape,
    ShapeKind,
    Slot,
)
from parrot_pipelines.planogram.identification import targets as targets_module
from parrot_pipelines.planogram.identification.targets import ocr_targets, read_target_text


class InlineExecutor:
    """Run submitted functions inline and record pool submissions."""

    def __init__(self, fail_calls: int = 0):
        self.calls = []
        self.fail_calls = fail_calls

    async def run(self, fn, *args):
        self.calls.append((fn, args))
        if self.fail_calls:
            self.fail_calls -= 1
            raise RuntimeError("executor failed")
        return fn(*args)


class _Ocr:
    available = True


def _box(x1, y1, x2, y2):
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0)


def _shape(shape_id, kind, box, membership=FixtureMembership.ON_FIXTURE):
    return Shape(shape_id=shape_id, image_id="img", kind=kind, box=box, membership=membership)


def _perception():
    slot = Slot(
        slot_id="slot-1", image_id="img", row_index=0, slot_index=1, box=_box(10, 10, 30, 30), anchor_shape_id="tag-1"
    )
    tag = _shape("tag-1", ShapeKind.PRICE_TAG, _box(40, 40, 60, 60))
    zone = _shape("zone-1", ShapeKind.ZONE, _box(70, 70, 90, 90))
    return PerceptionResult(image_id="img", shapes=[tag], slots=[slot], zones=[zone])


def _ctx(executor, layout=None):
    return CycleContext(executor=executor, ocr=_Ocr(), layout=layout)


def _fake_read(crop):
    return (f"v{int(crop.mean())}", 0.87) if crop.size else ("", 0.0)


def _empty_read(crop):
    return "", 0.0


@pytest.mark.asyncio
async def test_slot_text_comes_from_slot_box_not_anchor_tag(monkeypatch):
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    image[10:30, 10:30] = 50
    image[40:60, 40:60] = 150
    image[70:90, 70:90] = 220
    monkeypatch.setattr(targets_module, "read_crop", _fake_read)

    readings = await read_target_text(image, _perception(), _ctx(InlineExecutor()))

    assert readings["slot-1"].text == "v50"
    assert readings["tag-1"].text == "v150"
    assert readings["slot-1"].confidence == 0.87


@pytest.mark.asyncio
async def test_zone_and_tag_are_separate_targets(monkeypatch):
    monkeypatch.setattr(targets_module, "read_crop", _fake_read)

    readings = await read_target_text(np.zeros((100, 100, 3), dtype=np.uint8), _perception(), _ctx(InlineExecutor()))

    assert set(readings) == {"slot-1", "tag-1", "zone-1"}


def test_ocr_targets_respects_profile_subset():
    perception = _perception()
    assert ocr_targets(perception, ["zone"]) == [perception.zones[0]]
    no_slots = perception.model_copy(update={"slots": []})
    assert ocr_targets(no_slots, ["slot"]) == [perception.shapes[0]]


def test_ocr_targets_deduplicates_ids():
    zone = _perception().zones[0]
    perception = _perception().model_copy(update={"shapes": [zone]})

    assert ocr_targets(perception, ["zone", "tag"]) == [zone]


@pytest.mark.asyncio
async def test_ocr_unavailable_returns_empty_map(monkeypatch):
    executor = InlineExecutor()
    ctx = CycleContext(executor=executor, ocr=None)
    assert await read_target_text(np.zeros((10, 10, 3), dtype=np.uint8), _perception(), ctx) == {}
    ctx.ocr = type("UnavailableOcr", (), {"available": False})()
    assert await read_target_text(np.zeros((10, 10, 3), dtype=np.uint8), _perception(), ctx) == {}
    assert executor.calls == []


@pytest.mark.asyncio
async def test_batches_bounded_by_ocr_batch_size(monkeypatch):
    monkeypatch.setattr(targets_module, "read_crop", _fake_read)
    slots = [
        Slot(slot_id=f"slot-{index}", image_id="img", row_index=0, slot_index=index, box=_box(index, 0, index + 1, 1))
        for index in range(5)
    ]
    perception = PerceptionResult(image_id="img", slots=slots)
    layout = type("Layout", (), {"ocr_targets": ["slot"], "ocr_batch_size": 2})()
    executor = InlineExecutor()

    await read_target_text(np.zeros((10, 10, 3), dtype=np.uint8), perception, _ctx(executor, layout))

    assert len(executor.calls) == 5
    assert all(call[0] is targets_module.read_crop for call in executor.calls)


@pytest.mark.asyncio
async def test_executor_failure_is_isolated_and_recorded(monkeypatch):
    monkeypatch.setattr(targets_module, "read_crop", _fake_read)
    slots = [
        Slot(slot_id=f"slot-{index}", image_id="img", row_index=0, slot_index=index, box=_box(index, 0, index + 1, 1))
        for index in range(3)
    ]
    perception = PerceptionResult(image_id="img", slots=slots)
    layout = type("Layout", (), {"ocr_targets": ["slot"], "ocr_batch_size": 2})()
    ctx = _ctx(InlineExecutor(fail_calls=2), layout)

    readings = await read_target_text(np.zeros((10, 10, 3), dtype=np.uint8), perception, ctx)

    assert set(readings) == {"slot-2"}
    assert len(ctx.errors) == 1
    assert "ocr_failed" in ctx.errors[0]


@pytest.mark.asyncio
async def test_empty_text_is_not_empty_occupancy(monkeypatch):
    monkeypatch.setattr(targets_module, "read_crop", _empty_read)

    readings = await read_target_text(np.zeros((100, 100, 3), dtype=np.uint8), _perception(), _ctx(InlineExecutor()))

    assert readings["slot-1"].text == ""
    assert not hasattr(readings["slot-1"], "occupancy")
