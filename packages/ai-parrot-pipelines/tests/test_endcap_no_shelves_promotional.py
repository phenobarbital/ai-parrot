"""EndcapNoShelvesPromotional on the shared perceive -> identify -> compare cycle (FEAT-612)."""

from __future__ import annotations

import inspect
import logging
from unittest.mock import MagicMock

import pytest
from PIL import Image

from parrot.models.detections import AisleConfig, PlanogramDescription, DetectionBox
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus,
    ComparisonResult,
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FixtureMembership,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    Shape,
    ShapeKind,
)
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types import endcap_no_shelves_promotional as promo_module
from parrot_pipelines.planogram.types.endcap_no_shelves_promotional import EndcapNoShelvesPromotional


LEGACY = (
    "compute_roi",
    "detect_objects_roi",
    "detect_objects",
    "check_planogram_compliance",
    "_generate_virtual_shelves",
    "_assign_products_to_shelves",
)


class _RaisingVision:
    """Any attribute access fails: compare must not touch the provider."""

    def __getattr__(self, name: str):
        raise AssertionError(f"compare touched vision.{name}")


def _description() -> PlanogramDescription:
    return PlanogramDescription(brand="", category="promotional", aisle=AisleConfig(name="promotional"), shelves=[])


def _handler() -> EndcapNoShelvesPromotional:
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.promo")
    config = MagicMock()
    config.planogram_config = {}
    config.config_name = "promo-test"
    config.slots_definition = {}
    config.get_planogram_description.return_value = _description()
    return EndcapNoShelvesPromotional(pipeline=pipeline, config=config)


def _definition() -> object:
    return load_slots_definition(
        {
            "version": "1",
            "shelves": [],
            "zones": [
                {"zone_id": "header", "kind": "backlit", "required": True},
                {"zone_id": "base", "kind": "poster", "required": False},
            ],
        }
    )


def _layout():
    return _handler().default_layout_profile().model_copy(
        update={
            "zone_selectors": [
                {"zone_id": "header", "profile": "promo_backlit_zone", "kind": "zone", "ordinal": 0},
                {"zone_id": "base", "profile": "promo_poster_zone", "kind": "zone", "ordinal": 0},
            ]
        }
    )


def _ctx(bindings: list[RuleBinding], *, observation: RuleObservation | None = None) -> CycleContext:
    return CycleContext(
        vision=_RaisingVision(),
        definition=_definition(),
        bindings=bindings,
        layout=_layout(),
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
    ).model_copy(
        update={
            "images": {"img0": Image.new("RGB", (800, 600))},
        }
    )


def _header_perception() -> PerceptionResult:
    header = Shape(
        shape_id="header-shape",
        image_id="img0",
        kind=ShapeKind.ZONE,
        profile="promo_backlit_zone",
        box=DetectionBox(x1=10, y1=20, x2=400, y2=120, confidence=1.0),
        membership=FixtureMembership.ON_FIXTURE,
    )
    return PerceptionResult(image_id="img0", image_size=(800, 600), zones=[header])


def test_default_layout_profile_is_fresh_zone_only():
    first = EndcapNoShelvesPromotional.default_layout_profile()
    second = EndcapNoShelvesPromotional.default_layout_profile()
    assert first is not second and first.shape_profiles[0] is not second.shape_profiles[0]
    assert {profile.kind for profile in first.shape_profiles} == {"zone"}
    assert first.identify_strategy.value == "full_image"
    assert first.perception_mode == "cv" and first.min_usable_shapes == 1


def test_no_legacy_methods_and_no_hardcoded_elements():
    for name in LEGACY:
        assert name not in EndcapNoShelvesPromotional.__dict__
    source = inspect.getsource(promo_module)
    for literal in ("backlit_panel", "lower_poster", "_EXPECTED_ELEMENTS", "Epson"):
        assert literal not in source


async def test_hooks_delegate_to_shared_stages(monkeypatch):
    calls: dict[str, tuple] = {}
    perception = PerceptionResult(image_id="img0")
    identification = IdentificationResult(image_id="img0")
    image = Image.new("RGB", (10, 10))
    ctx = CycleContext()

    async def fake_perceive(received_image, image_id, received_ctx):
        calls["perceive"] = (received_image, image_id, received_ctx)
        return perception

    async def fake_identify(received_image, received_perception, received_ctx):
        calls["identify"] = (received_image, received_perception, received_ctx)
        return identification

    def fake_compare(received_perceptions, received_identifications, received_ctx, description):
        calls["compare"] = (received_perceptions, received_identifications, received_ctx, description)
        return ComparisonResult()

    monkeypatch.setattr(promo_module, "perceive_image", fake_perceive)
    monkeypatch.setattr(promo_module, "identify_image", fake_identify)
    monkeypatch.setattr(promo_module, "compare_observations", fake_compare)
    handler = _handler()

    assert await handler.perceive(image, "img0", ctx) is perception
    assert await handler.identify(image, perception, ctx) is identification
    assert await handler.compare([perception], [identification], ctx)
    assert calls["perceive"] == (image, "img0", ctx)
    assert calls["identify"] == (image, perception, ctx)
    assert calls["compare"][:3] == ([perception], [identification], ctx)
    assert isinstance(calls["compare"][3], PlanogramDescription)


async def test_optional_zone_absent_still_compliant():
    bindings = [
        RuleBinding(rule_id="present", kind="zone_present", target_id="header"),
        RuleBinding(rule_id="illumination", kind="illumination", target_id="header", params={"required": "on"}),
    ]
    observation = RuleObservation(
        image_id="img0", target_id="header-shape", kind="illumination", value="on", assessed=True, source=ObservationSource.LLM
    )
    result = await _handler().compare(
        [_header_perception()],
        [IdentificationResult(image_id="img0", rule_observations=[observation])],
        _ctx(bindings),
    )
    assert result.overall_compliant is True
    assert not any(outcome.rule_id.startswith("base") for shelf in result.shelf_scores for outcome in shelf.rule_results)


async def test_illumination_off_fails_mandatory_rule():
    binding = RuleBinding(rule_id="illumination", kind="illumination", target_id="header", params={"required": "on"})
    observation = RuleObservation(
        image_id="img0", target_id="header-shape", kind="illumination", value="off", assessed=True, source=ObservationSource.LLM
    )
    result = await _handler().compare(
        [_header_perception()],
        [IdentificationResult(image_id="img0", rule_observations=[observation])],
        _ctx([binding]),
    )
    outcome = next(outcome for shelf in result.shelf_scores for outcome in shelf.rule_results if outcome.rule_id == "illumination")
    assert result.overall_compliant is False
    assert outcome.assessed is True and outcome.passed is False


async def test_unknown_illumination_is_inconclusive():
    binding = RuleBinding(rule_id="illumination", kind="illumination", target_id="header", params={"required": "on"})
    result = await _handler().compare(
        [_header_perception()],
        [IdentificationResult(image_id="img0")],
        _ctx([binding]),
    )
    assert result.assessment_status == AssessmentStatus.INCONCLUSIVE
    assert result.overall_compliant is False


def test_type_registered():
    assert PlanogramCompliance._PLANOGRAM_TYPES["endcap_no_shelves_promotional"] is EndcapNoShelvesPromotional
