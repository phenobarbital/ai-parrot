"""GraphicPanelDisplay on the shared cycle: zone-only, evidence-based text and illumination (FEAT-612, Module 9)."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock
from typing import List, Optional

import pytest

from parrot.models.detections import DetectionBox
from parrot.pipelines.planogram.types.graphic_panel_display import GraphicPanelDisplay
from parrot.pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.comparison.definition import RuleBinding, SlotsDefinition, load_slots_definition
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus,
    CycleContext,
    FixtureMembership,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    Shape,
    ShapeKind,
)
from parrot_pipelines.planogram.layout import ZoneSelector
from parrot_pipelines.planogram.types import graphic_panel_display as panel_module

LEGACY = (
    "compute_roi",
    "detect_objects_roi",
    "detect_objects",
    "check_planogram_compliance",
    "_generate_virtual_shelves",
    "_assign_products_to_shelves",
    "_find_display_roi",
    "_check_illumination_from_roi",
    "_enrich_zone",
    "_get_illumination_penalty",
)
ZONE_KINDS = ("graphic", "backlit", "advertisement")


class _RaisingVision:
    def __getattr__(self, name):
        raise AssertionError(f"compare touched vision.{name}")


def _shape(index: int, text: Optional[str] = None) -> Shape:
    return Shape(
        shape_id=f"img0:zone{index}",
        image_id="img0",
        kind=ShapeKind.ZONE,
        box=DetectionBox(x1=10, y1=10 + index * 60, x2=190, y2=50 + index * 60, confidence=1.0),
        membership=FixtureMembership.ON_FIXTURE,
        source=ObservationSource.CV,
        ocr_text=text,
    )


def _definition(kinds=ZONE_KINDS) -> SlotsDefinition:
    return load_slots_definition(
        {"version": "1", "zones": [{"zone_id": f"z{i}", "kind": k} for i, k in enumerate(kinds)]}
    )


def _perception(count: int, texts: Optional[List[Optional[str]]] = None) -> PerceptionResult:
    texts = texts or [None] * count
    return PerceptionResult(image_id="img0", image_size=(200, 400), zones=[_shape(i, texts[i]) for i in range(count)])


def _ctx(definition, bindings) -> CycleContext:
    layout = GraphicPanelDisplay.default_layout_profile().model_copy(
        update={
            "zone_selectors": [
                ZoneSelector(zone_id=z.zone_id, kind="zone", ordinal=i) for i, z in enumerate(definition.zones)
            ]
        }
    )
    return CycleContext(vision=_RaisingVision(), definition=definition, bindings=bindings, layout=layout)


def _presence(definition) -> List[RuleBinding]:
    return [RuleBinding(rule_id=f"p-{z.zone_id}", kind="zone_present", target_id=z.zone_id) for z in definition.zones]


def _obs(target: str, kind: str, value, assessed: bool = True) -> RuleObservation:
    return RuleObservation(
        image_id="img0", target_id=target, kind=kind, value=value, assessed=assessed, source=ObservationSource.CV
    )


def _type() -> GraphicPanelDisplay:
    config = MagicMock()
    config.get_planogram_description.side_effect = ValueError("no shelves")
    config.planogram_config = {}
    return GraphicPanelDisplay(MagicMock(), config)


async def _compare(definition, bindings, perception, observations=()):
    ctx = _ctx(definition, bindings)
    ident = IdentificationResult(image_id="img0", rule_observations=list(observations))
    return await _type().compare([perception], [ident], ctx)


class TestDefaultLayout:
    def test_zone_only_and_fresh(self):
        a, b = GraphicPanelDisplay.default_layout_profile(), GraphicPanelDisplay.default_layout_profile()
        assert a is not b
        assert a.shape_profiles[0] is not b.shape_profiles[0]
        assert {p.kind for p in a.shape_profiles} == {"zone"}
        assert a.min_usable_shapes == 1 and a.perception_mode == "cv" and a.identify_strategy.value == "full_image"

    def test_compat_classvars(self):
        assert GraphicPanelDisplay.requires_slots_definition is True
        assert GraphicPanelDisplay.uses_enhanced_image is False
        assert GraphicPanelDisplay.min_usable_shapes == 1


class TestNoLegacyContract:
    def test_legacy_members_removed(self):
        for name in LEGACY:
            assert name not in GraphicPanelDisplay.__dict__
        source = inspect.getsource(panel_module)
        assert "_DEFAULT_ILLUMINATION_PENALTY" not in source and "ask_to_image" not in source


class TestZoneEvidence:
    @pytest.mark.asyncio
    async def test_hooks_delegate_to_shared_stages(self, monkeypatch):
        seen = {}

        async def fake_perceive(image, image_id, ctx):
            seen["perceive"] = (image, image_id, ctx)
            return "P"

        async def fake_identify(image, perception, ctx):
            seen["identify"] = (image, perception, ctx)
            return "I"

        def fake_compare(perceptions, identifications, ctx, description):
            seen["compare"] = (perceptions, identifications, ctx, description)
            return "C"

        monkeypatch.setattr(panel_module, "perceive_image", fake_perceive)
        monkeypatch.setattr(panel_module, "identify_image", fake_identify)
        monkeypatch.setattr(panel_module, "compare_observations", fake_compare)
        ctx = CycleContext()
        panel = _type()
        monkeypatch.setattr(GraphicPanelDisplay, "_description", lambda self: "D")
        assert await panel.perceive("img", "img0", ctx) == "P"
        assert await panel.identify("img", "P", ctx) == "I"
        assert await panel.compare(["P"], ["I"], ctx) == "C"
        assert seen["perceive"][2] is ctx and seen["identify"][2] is ctx and seen["compare"][2] is ctx
        assert seen["compare"][3] == "D"

    @pytest.mark.asyncio
    async def test_all_configured_zones_present_is_compliant(self):
        definition = _definition()
        result = await _compare(definition, _presence(definition), _perception(3))
        assert result.overall_compliant is True
        assert result.detected_products == 0
        assert result.position_results == []

    @pytest.mark.asyncio
    async def test_missing_zone_only_fails_when_region_inspected(self):
        definition = _definition(("advertisement",))
        bindings = _presence(definition)
        inspected = _obs("img0:zone-region:z0", "zone_present", False)
        failed = await _compare(definition, bindings, _perception(0), [inspected])
        assert failed.overall_compliant is False
        assert failed.assessment_status == AssessmentStatus.COMPLETE
        unknown = await _compare(definition, bindings, _perception(0))
        assert unknown.overall_compliant is False
        assert unknown.assessment_status == AssessmentStatus.INCONCLUSIVE


class TestIllumination:
    def _setup(self):
        definition = _definition(("backlit",))
        bindings = _presence(definition) + [
            RuleBinding(rule_id="ill", kind="illumination", target_id="z0", params={"required": "on", "penalty": 1.0})
        ]
        return definition, bindings

    @pytest.mark.asyncio
    async def test_off_when_on_required_fails(self):
        definition, bindings = self._setup()
        result = await _compare(definition, bindings, _perception(1), [_obs("img0:zone0", "illumination", "off")])
        assert result.overall_compliant is False
        assert result.assessment_status == AssessmentStatus.COMPLETE

    @pytest.mark.asyncio
    async def test_matching_state_passes(self):
        definition, bindings = self._setup()
        result = await _compare(definition, bindings, _perception(1), [_obs("img0:zone0", "illumination", "on")])
        assert result.overall_compliant is True

    @pytest.mark.asyncio
    async def test_unknown_state_is_inconclusive(self):
        definition, bindings = self._setup()
        result = await _compare(definition, bindings, _perception(1))
        assert result.assessment_status == AssessmentStatus.INCONCLUSIVE
        assert result.overall_compliant is False


class TestTextRequirements:
    @pytest.mark.asyncio
    async def test_mandatory_text_missing_fails(self):
        definition = _definition(("graphic",))
        bindings = _presence(definition) + [
            RuleBinding(
                rule_id="txt",
                kind="text_requirements",
                target_id="z0",
                params={"requirements": [{"required_text": "EPSON", "match_type": "contains"}]},
            )
        ]
        bad = await _compare(definition, bindings, _perception(1, ["hello world"]))
        assert bad.overall_compliant is False
        good = await _compare(definition, bindings, _perception(1, ["EPSON ink"]))
        assert good.overall_compliant is True


# ---------------------------------------------------------------------------
# Tests: type registration
# ---------------------------------------------------------------------------


class TestRegistration:
    """Verify GraphicPanelDisplay is registered in _PLANOGRAM_TYPES."""

    def test_type_registered(self):
        """'graphic_panel_display' key must exist in PlanogramCompliance._PLANOGRAM_TYPES."""
        assert "graphic_panel_display" in PlanogramCompliance._PLANOGRAM_TYPES

    def test_type_resolves_to_correct_class(self):
        """_PLANOGRAM_TYPES['graphic_panel_display'] must be GraphicPanelDisplay."""
        cls = PlanogramCompliance._PLANOGRAM_TYPES["graphic_panel_display"]
        assert cls is GraphicPanelDisplay

    def test_product_on_shelves_still_registered(self):
        """Existing 'product_on_shelves' registration must not be broken."""
        assert "product_on_shelves" in PlanogramCompliance._PLANOGRAM_TYPES
