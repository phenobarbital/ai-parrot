"""Shared CV perception, geometry rebuild and usable-target counting (FEAT-612, Module 2)."""

import pickle
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PIL import Image

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.contracts import (
    CycleContext,
    FixtureMembership,
    ObservationSource,
    PerceptionResult,
    Shape,
    ShapeKind,
)
from parrot_pipelines.planogram.layout import LayoutProfile, ZoneSelector
from parrot_pipelines.planogram.perception.profiles import PRICE_TAG_PROFILE
from parrot_pipelines.planogram.perception.slots import AnchorRule
from parrot_pipelines.planogram.stages import perceive as stage
from parrot_pipelines.planogram.stages.perceive import count_usable_targets, perceive_image, rebuild_geometry

W, H = 2000, 1400
TAG_TOPS = (380, 760, 1100)
PITCH = 220
GAP = (1, 3)


class _InlineExecutor:
    """Run CPU helpers inline because worker processes lack worktree Cython builds."""

    async def run(self, fn, *args):
        """Return the direct result of the supplied CPU helper."""
        return fn(*args)


class _RaisingVision:
    """Raise when CV mode incorrectly asks the vision adapter."""

    async def ask(self, *args, **kwargs):
        """Fail the test when vision is used unexpectedly."""
        raise AssertionError("vision must not be called")


def _ink_profile(**overrides) -> LayoutProfile:
    """Return the price-tag profile used by the synthetic fixture."""
    base = dict(
        shape_profiles=[PRICE_TAG_PROFILE],
        anchor_rule=AnchorRule.TAG_BELOW_PRODUCT,
        fill_gaps=True,
        untagged_bottom_row=True,
        min_row_items=4,
    )
    return LayoutProfile(**{**base, **overrides})


def _ctx(profile: LayoutProfile, vision=None) -> CycleContext:
    """Build a cycle context with deterministic inline CPU execution."""
    return CycleContext(vision=vision or _RaisingVision(), executor=_InlineExecutor(), layout=profile)


@pytest.fixture
def ink_image() -> Image.Image:
    """Return a 3x8 bright tag wall with a single visible gap."""
    image = np.full((H, W, 3), 40, np.uint8)
    for row, top in enumerate(TAG_TOPS):
        for col in range(8):
            if (row, col) == GAP:
                continue
            x = 150 + col * PITCH
            cv2.rectangle(image, (x, top), (x + 110, top + 40), (245, 245, 245), -1)
            cv2.line(image, (x + 8, top + 20), (x + 102, top + 20), (20, 20, 20), 3)
    return Image.fromarray(image[:, :, ::-1].copy())


def _shape(shape_id, kind, box, source=ObservationSource.LLM, profile="llm_detector") -> Shape:
    """Build one source-pixel shape for geometry tests."""
    return Shape(
        shape_id=shape_id,
        image_id="img0",
        kind=kind,
        box=DetectionBox(x1=box[0], y1=box[1], x2=box[2], y2=box[3], confidence=0.9),
        profile=profile,
        source=source,
    )


async def test_cv_tag_below_geometry_matches_ink_wall(ink_image):
    """CV tag geometry retains the InkWall slot layout."""
    perception = await perceive_image(ink_image, "img0", _ctx(_ink_profile()))
    assert perception.detection_source == "cv"
    assert perception.row_count == 3
    assert len([shape for shape in perception.shapes if shape.kind == ShapeKind.PRICE_TAG]) == 23
    rows = [[slot for slot in perception.slots if slot.row_index == index] for index in range(4)]
    assert [len(row) for row in rows] == [8, 8, 8, 8]
    assert sum(slot.inferred for slot in rows[1]) == 1
    assert all(slot.inferred for slot in rows[3])
    assert all(
        slot.anchor_shape_id in {shape.shape_id for shape in perception.shapes}
        for slot in perception.slots
        if not slot.inferred
    )


async def test_bottom_row_is_not_synthesized_past_the_definition(ink_image):
    """With every shelf of the definition anchored, the room below the wall is not a row."""
    shelf = SimpleNamespace(facings=["facing"])
    open_ctx = _ctx(_ink_profile())
    full_ctx = _ctx(_ink_profile()).model_copy(update={"definition": SimpleNamespace(shelves=[shelf] * 3)})
    taller_ctx = _ctx(_ink_profile()).model_copy(update={"definition": SimpleNamespace(shelves=[shelf] * 4)})
    assert len({slot.row_index for slot in (await perceive_image(ink_image, "img0", open_ctx)).slots}) == 4
    assert len({slot.row_index for slot in (await perceive_image(ink_image, "img0", full_ctx)).slots}) == 3
    assert len({slot.row_index for slot in (await perceive_image(ink_image, "img0", taller_ctx)).slots}) == 4


async def test_profile_overrides_reach_primitives(ink_image):
    """Profile row and slot options affect the shared geometry primitive calls."""
    no_gaps = await perceive_image(ink_image, "img0", _ctx(_ink_profile(fill_gaps=False)))
    no_bottom = await perceive_image(ink_image, "img0", _ctx(_ink_profile(untagged_bottom_row=False)))
    no_rows = await perceive_image(ink_image, "img0", _ctx(_ink_profile(min_row_items=9)))
    assert len([slot for slot in no_gaps.slots if slot.row_index == 1]) == 7
    assert no_bottom.row_count == 3 and len({slot.row_index for slot in no_bottom.slots}) == 3
    assert no_rows.row_count == 0 and not no_rows.slots


async def test_rebuild_geometry_keeps_llm_anchor_ids(ink_image):
    """Fallback geometry remaps generated candidate anchors to LLM shape ids."""
    profile = LayoutProfile(shape_profiles=[], anchor_rule=AnchorRule.SHAPE_IS_SLOT, perception_mode="llm_detector")
    shapes = [
        _shape(f"img0:llm:{index}", ShapeKind.PRODUCT, (100 + index * 200, 300, 250 + index * 200, 500))
        for index in range(3)
    ]
    perception = await rebuild_geometry(ink_image, shapes, "img0", _ctx(profile), detection_source="llm")
    assert {slot.anchor_shape_id for slot in perception.slots} == {shape.shape_id for shape in shapes}
    assert all(shape.row_index == 0 and shape.slot_index is not None for shape in perception.shapes)
    assert perception.detection_source == "llm"


async def test_mixed_source_when_cv_zones_retained(ink_image):
    """Zones participate in provenance even though they are not product anchors."""
    profile = LayoutProfile(shape_profiles=[], anchor_rule=AnchorRule.SHAPE_IS_SLOT, perception_mode="llm_detector")
    shapes = [
        _shape("img0:llm:1", ShapeKind.PRODUCT, (100, 300, 250, 500)),
        _shape("img0:cv:zone", ShapeKind.ZONE, (0, 0, 500, 200), ObservationSource.CV, "zone"),
    ]
    perception = await rebuild_geometry(ink_image, shapes, "img0", _ctx(profile), detection_source="llm")
    assert perception.detection_source == "mixed"


def test_count_usable_targets_excludes_off_fixture_and_tags():
    """Only on-fixture targets relevant to the active anchor rule suppress fallback."""
    shapes = [
        _shape("product-1", ShapeKind.PRODUCT, (0, 0, 10, 10)).model_copy(
            update={"membership": FixtureMembership.ON_FIXTURE}
        ),
        _shape("product-2", ShapeKind.PRODUCT, (20, 0, 30, 10)).model_copy(
            update={"membership": FixtureMembership.ON_FIXTURE}
        ),
        _shape("product-off", ShapeKind.PRODUCT, (40, 0, 50, 10)).model_copy(
            update={"membership": FixtureMembership.OFF_FIXTURE}
        ),
        _shape("fact", ShapeKind.FACT_TAG, (60, 0, 70, 10)).model_copy(
            update={"membership": FixtureMembership.ON_FIXTURE}
        ),
        _shape("tag", ShapeKind.PRICE_TAG, (80, 0, 90, 10)).model_copy(
            update={"membership": FixtureMembership.ON_FIXTURE}
        ),
    ]
    perception = PerceptionResult(shapes=shapes)
    slot_profile = LayoutProfile(
        shape_profiles=[], anchor_rule=AnchorRule.SHAPE_IS_SLOT, perception_mode="llm_detector"
    )
    tag_profile = LayoutProfile(
        shape_profiles=[], anchor_rule=AnchorRule.TAG_BELOW_PRODUCT, perception_mode="llm_detector"
    )
    assert count_usable_targets(perception, slot_profile) == 2
    assert count_usable_targets(perception, tag_profile) == 1


def test_zone_only_counts_matched_zones():
    """Zone-only profiles count selector-confirmed zones only when selectors exist."""
    selector = ZoneSelector(zone_id="z1", region=(0.0, 0.0, 0.5, 0.5))
    profile = LayoutProfile(
        shape_profiles=[PRICE_TAG_PROFILE.model_copy(update={"name": "zone", "kind": "zone"})],
        perception_mode="llm_detector",
        zone_selectors=[selector],
    )
    zones = [
        _shape("zone-1", ShapeKind.ZONE, (0, 0, 100, 100)).model_copy(
            update={"membership_evidence": ["zone_selector:z1"]}
        ),
        _shape("zone-2", ShapeKind.ZONE, (100, 100, 200, 200)),
    ]
    perception = PerceptionResult(zones=zones)
    assert count_usable_targets(perception, profile) == 1
    assert count_usable_targets(perception, profile.model_copy(update={"zone_selectors": []})) == 2


async def test_selector_ordinal_requires_full_view(ink_image):
    """Repeated selector groups refuse partial observed views."""
    selectors = [ZoneSelector(zone_id=f"z{index}", kind="zone", ordinal=index) for index in range(2)]
    profile = LayoutProfile(shape_profiles=[], perception_mode="llm_detector", zone_selectors=selectors)
    zone = _shape("img0:zone:1", ShapeKind.ZONE, (10, 10, 100, 100), ObservationSource.CV, "zone")
    perception = await rebuild_geometry(ink_image, [zone], "img0", _ctx(profile), detection_source="cv")
    assert not perception.zones[0].membership_evidence


async def test_llm_detector_mode_calls_detector_once(ink_image, monkeypatch):
    """Configured LLM mode invokes detector once and reports an empty detection result."""
    calls = 0

    async def detect_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(stage, "llm_detect_shapes", detect_once)
    profile = LayoutProfile(shape_profiles=[], perception_mode="llm_detector")
    result = await perceive_image(ink_image, "img0", _ctx(profile))
    assert calls == 1
    assert result.errors == ["img0: llm_detector produced no shapes"]


def test_cpu_helpers_are_picklable():
    """Executor-dispatched wrappers remain safe for process-worker pickling."""
    for fn in (stage._to_bgr, stage._propose, stage._group_rows):
        assert pickle.loads(pickle.dumps(fn)) is fn


async def test_missing_layout_raises(ink_image):
    """Missing resolved layout fails rather than silently selecting a default profile."""
    with pytest.raises(ValueError, match="layout"):
        await perceive_image(ink_image, "img0", CycleContext(executor=_InlineExecutor()))
