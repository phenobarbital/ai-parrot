"""Neutral evidence collection tests for the shared identification stage."""

import asyncio

import numpy as np
import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.planogram.comparison.definition import RuleBinding
from parrot_pipelines.planogram.contracts import (
    CycleContext,
    FixtureMembership,
    ObservationSource,
    PerceptionResult,
    Shape,
    ShapeKind,
)
from parrot_pipelines.planogram.identification.evidence import (
    EVIDENCE_STAGE,
    RegionPresenceAnswer,
    ZoneEvidenceAnswer,
    collect_rule_evidence,
)
from parrot_pipelines.planogram.identification.vision import VisionError
from parrot_pipelines.planogram.layout import LayoutProfile, ZoneSelector
from parrot_pipelines.planogram.perception.profiles import PRICE_TAG_PROFILE


class InlineExecutor:
    """Run crop helpers inline for deterministic tests."""

    async def run(self, fn, *args):
        """Invoke the supplied CPU helper directly."""
        return fn(*args)


class RecordingVision:
    """Return queued evidence answers while retaining the provider prompts."""

    def __init__(self, *answers):
        """Store answer values or exceptions in their requested order."""
        self.answers = list(answers)
        self.prompts = []

    async def ask(self, prompt, images, schema, *, stage, prompt_version, system_prompt=None):
        """Record a structured request and return its queued answer."""
        assert stage == EVIDENCE_STAGE
        self.prompts.append(prompt)
        item = self.answers.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _zone(identifier="img0:zone0", membership=FixtureMembership.ON_FIXTURE, box=(20, 10, 380, 80)):
    """Build one observed zone in source pixels."""
    return Shape(
        shape_id=identifier,
        image_id="img0",
        kind=ShapeKind.ZONE,
        box=DetectionBox(x1=box[0], y1=box[1], x2=box[2], y2=box[3], confidence=1.0),
        membership=membership,
        source=ObservationSource.CV,
    )


def _layout(**overrides):
    """Build a validated test profile."""
    return LayoutProfile(shape_profiles=[PRICE_TAG_PROFILE], **overrides)


def _ctx(vision, bindings, layout=None):
    """Build the run-local services used by evidence collection."""
    return CycleContext(vision=vision, executor=InlineExecutor(), bindings=bindings, layout=layout)


def _perception(*zones):
    """Build the image's observed zones."""
    return PerceptionResult(image_id="img0", image_size=(400, 300), zones=list(zones))


@pytest.mark.asyncio
async def test_no_bindings_make_no_provider_calls():
    """No evidence kind means no crop or provider call."""
    vision = RecordingVision()
    assert await collect_rule_evidence(np.zeros((300, 400, 3), np.uint8), _perception(_zone()), _ctx(vision, [])) == []
    assert vision.prompts == []


@pytest.mark.asyncio
async def test_illumination_observation_is_neutral():
    """Illumination describes the observed crop without leaking binding expectations."""
    binding = RuleBinding(
        rule_id="r0", kind="illumination", target_id="zone_header", params={"required": "off", "penalty": 0.3}
    )
    vision = RecordingVision(ZoneEvidenceAnswer(illumination="on"))
    observations = await collect_rule_evidence(np.zeros((300, 400, 3), np.uint8), _perception(_zone()), _ctx(vision, [binding]))
    assert observations[0].kind == "illumination"
    assert observations[0].value == "on" and observations[0].assessed
    assert observations[0].target_id == "img0:zone0"
    prompt = vision.prompts[0].lower()
    assert "required" not in prompt and "zone_header" not in prompt and "0.3" not in prompt


@pytest.mark.asyncio
async def test_unknown_illumination_is_unassessed():
    """An unknown visible state remains an unassessed observation."""
    binding = RuleBinding(rule_id="r0", kind="illumination", target_id="zone_header")
    vision = RecordingVision(ZoneEvidenceAnswer(illumination="unknown"))
    observations = await collect_rule_evidence(np.zeros((300, 400, 3), np.uint8), _perception(_zone()), _ctx(vision, [binding]))
    assert observations[0].assessed is False


@pytest.mark.asyncio
async def test_visual_features_are_recorded_as_seen():
    """Feature observations preserve the model's visible phrases."""
    binding = RuleBinding(rule_id="r0", kind="visual_features", target_id="zone_header")
    vision = RecordingVision(ZoneEvidenceAnswer(visual_features=["blue logo", "header text"]))
    observations = await collect_rule_evidence(np.zeros((300, 400, 3), np.uint8), _perception(_zone()), _ctx(vision, [binding]))
    assert observations[0].value == ["blue logo", "header text"]
    assert observations[0].target_id == "img0:zone0" and observations[0].assessed


@pytest.mark.asyncio
async def test_off_fixture_zone_is_not_inspected():
    """Off-fixture zones cannot create rule evidence."""
    binding = RuleBinding(rule_id="r0", kind="illumination", target_id="zone_header")
    vision = RecordingVision()
    observations = await collect_rule_evidence(
        np.zeros((300, 400, 3), np.uint8),
        _perception(_zone(membership=FixtureMembership.OFF_FIXTURE)),
        _ctx(vision, [binding]),
    )
    assert observations == [] and vision.prompts == []


@pytest.mark.asyncio
async def test_failed_crop_is_isolated():
    """A failed crop records an error while later zones still yield evidence."""
    binding = RuleBinding(rule_id="r0", kind="illumination", target_id="zone_header")
    vision = RecordingVision(VisionError("unavailable"), ZoneEvidenceAnswer(illumination="off"))
    ctx = _ctx(vision, [binding])
    observations = await collect_rule_evidence(
        np.zeros((300, 400, 3), np.uint8), _perception(_zone(), _zone("img0:zone1", box=(20, 100, 380, 180))), ctx
    )
    assert [observation.target_id for observation in observations] == ["img0:zone1"]
    assert "evidence_failed" in ctx.errors[0]


@pytest.mark.asyncio
async def test_region_is_inspected_only_without_an_observed_zone():
    """A configured region is inspected only where no eligible zone centre exists."""
    binding = RuleBinding(rule_id="r0", kind="zone_present", target_id="zone_header")
    layout = _layout(zone_selectors=[ZoneSelector(zone_id="zone_header", region=(0.0, 0.0, 1.0, 0.3))])
    blocked = RecordingVision()
    assert await collect_rule_evidence(np.zeros((300, 400, 3), np.uint8), _perception(_zone()), _ctx(blocked, [binding], layout)) == []
    vision = RecordingVision(RegionPresenceAnswer(present="no"))
    observations = await collect_rule_evidence(np.zeros((300, 400, 3), np.uint8), _perception(), _ctx(vision, [binding], layout))
    assert observations[0].target_id == "img0:zone-region:zone_header"
    assert observations[0].value is False and observations[0].assessed


@pytest.mark.asyncio
async def test_region_unknown_stays_unassessed():
    """Unknown region occupancy does not become negative evidence."""
    binding = RuleBinding(rule_id="r0", kind="zone_present", target_id="zone_header")
    layout = _layout(zone_selectors=[ZoneSelector(zone_id="zone_header", region=(0.0, 0.0, 1.0, 0.3))])
    vision = RecordingVision(RegionPresenceAnswer(present="unknown"))
    observations = await collect_rule_evidence(np.zeros((300, 400, 3), np.uint8), _perception(), _ctx(vision, [binding], layout))
    assert observations[0].value is None and observations[0].assessed is False


@pytest.mark.asyncio
async def test_cancellation_propagates():
    """Cancellation must remain visible to the run orchestrator."""
    binding = RuleBinding(rule_id="r0", kind="illumination", target_id="zone_header")
    vision = RecordingVision(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await collect_rule_evidence(np.zeros((300, 400, 3), np.uint8), _perception(_zone()), _ctx(vision, [binding]))
