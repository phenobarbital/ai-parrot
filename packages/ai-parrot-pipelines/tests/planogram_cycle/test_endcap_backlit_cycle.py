"""Offline cycle tests for EndcapBacklitMultitier (FEAT-612, Module 7)."""

import logging
from unittest.mock import MagicMock

import pytest

from parrot.models.detections import DetectionBox
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram import plan as plan_module
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.contracts import (
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FixtureMembership,
    Identification,
    IdentificationResult,
    IdentifyStrategy,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    Shape,
    ShapeKind,
    Slot,
)
from parrot_pipelines.planogram.perception.slots import AnchorRule
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types import endcap_backlit_multitier as backlit_module
from parrot_pipelines.planogram.types.endcap_backlit_multitier import EndcapBacklitMultitier


class _InlineExecutor:
    def __init__(self, max_workers: int = 2) -> None:
        self.max_workers = max_workers

    async def run(self, fn, *args):
        return fn(*args)

    async def aclose(self) -> None:
        return None


class _NoOcr:
    available = False


class _RaisingVision:
    def __getattr__(self, name):
        raise AssertionError(f"compare must not touch vision ({name})")


def _definition_dict() -> dict:
    """Generic header zone + one shelf of two facings (fictitious ids, no retailer data)."""
    facings = [
        {
            "facing_id": f"s1_f{slot}",
            "shelf_id": "s1",
            "slot": slot,
            "product": f"P-{slot}",
            "brand": "Acme",
            "descriptors": {"display_name": f"Product {slot}", "identifiers": [f"P-{slot}"]},
        }
        for slot in (1, 2)
    ]
    return {
        "version": "1",
        "shelves": [
            {"shelf_id": "header", "shelf_number": 0, "level": "header", "facings": []},
            {"shelf_id": "s1", "shelf_number": 1, "level": "s1", "facings": facings},
        ],
        "zones": [{"zone_id": "header_light", "kind": "backlit", "shelf_id": "header", "required": True}],
    }


def _box(x1, y1, x2, y2) -> DetectionBox:
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=0.9)


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(plan_module, "CpuExecutor", _InlineExecutor)
    monkeypatch.setattr(plan_module, "OcrReader", _NoOcr)


def _handler(definition: dict | None = None) -> EndcapBacklitMultitier:
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test-backlit")
    config = PlanogramConfig(
        planogram_type="endcap_backlit_multitier",
        planogram_config={},
        slots_definition=definition if definition is not None else _definition_dict(),
    )
    return EndcapBacklitMultitier(pipeline, config)


def _ctx(vision=None, definition=None, bindings=None) -> CycleContext:
    return CycleContext(
        vision=vision,
        executor=_InlineExecutor(),
        ocr=_NoOcr(),
        definition=definition,
        bindings=bindings or [],
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
    )


def test_default_layout_profile_backlit_defaults():
    first, second = EndcapBacklitMultitier.default_layout_profile(), EndcapBacklitMultitier.default_layout_profile()
    assert first is not second and first.shape_profiles[0] is not second.shape_profiles[0]
    assert {p.kind for p in first.shape_profiles} == {"product", "box", "fact_tag", "zone"}
    assert first.anchor_rule == AnchorRule.SHAPE_IS_SLOT and first.identify_strategy == IdentifyStrategy.STRIPS
    assert first.perception_mode == "cv" and first.min_usable_shapes == 3


def test_legacy_contract_removed():
    handler_cls = EndcapBacklitMultitier
    for name in ("compute_roi", "detect_objects_roi", "detect_objects", "check_planogram_compliance"):
        assert name not in vars(handler_cls)
    assert not hasattr(backlit_module, "_RawDetections")


def test_missing_definition_fails_fast(fake_vision_client):
    with pytest.raises(ValueError):
        PlanogramCompliance(
            planogram_config=PlanogramConfig(planogram_type="endcap_backlit_multitier", planogram_config={}),
            llm=fake_vision_client,
        )


def test_drop_fact_tag_misdetections_keeps_occluded_product():
    tag = Shape(shape_id="t", image_id="img0", kind=ShapeKind.FACT_TAG, box=_box(100, 300, 160, 320))
    fake = Shape(shape_id="p1", image_id="img0", kind=ShapeKind.PRODUCT, box=_box(98, 298, 162, 322))  # tag-sized
    tall = Shape(shape_id="p2", image_id="img0", kind=ShapeKind.PRODUCT, box=_box(90, 150, 170, 322))  # tag low
    kept = EndcapBacklitMultitier._drop_fact_tag_misdetections([tag, fake, tall])
    assert [s.shape_id for s in kept] == ["t", "p2"]


def _shapes():
    tag = Shape(shape_id="t", image_id="img0", kind=ShapeKind.FACT_TAG, box=_box(100, 300, 160, 320))
    fake = Shape(shape_id="p1", image_id="img0", kind=ShapeKind.PRODUCT, box=_box(98, 298, 162, 322))
    tall = Shape(shape_id="p2", image_id="img0", kind=ShapeKind.PRODUCT, box=_box(90, 150, 170, 322))
    zone = Shape(shape_id="z0", image_id="img0", kind=ShapeKind.ZONE, box=_box(0, 0, 800, 120))
    return tag, fake, tall, zone


async def test_perceive_rebuilds_geometry_only_after_a_drop(monkeypatch):
    from PIL import Image

    tag, fake, tall, zone = _shapes()
    calls = []

    async def fake_perceive(image, image_id, ctx):
        return PerceptionResult(image_id=image_id, image_size=image.size, shapes=[tag, fake, tall], zones=[zone])

    async def fake_rebuild(image, shapes, image_id, ctx, *, detection_source):
        calls.append({s.shape_id for s in shapes})
        return PerceptionResult(image_id=image_id, image_size=image.size, shapes=[s for s in shapes if s is not zone])

    monkeypatch.setattr(backlit_module, "perceive_image", fake_perceive)
    monkeypatch.setattr(backlit_module, "rebuild_geometry", fake_rebuild)
    handler = _handler()
    ctx = _ctx(definition=load_slots_definition(_definition_dict()))
    await handler.perceive(Image.new("RGB", (800, 600)), "img0", ctx)
    assert calls == [{"t", "p2", "z0"}]

    calls.clear()

    async def clean_perceive(image, image_id, ctx):
        return PerceptionResult(image_id=image_id, image_size=image.size, shapes=[tag, tall], zones=[zone])

    monkeypatch.setattr(backlit_module, "perceive_image", clean_perceive)
    await handler.perceive(Image.new("RGB", (800, 600)), "img0", ctx)
    assert calls == []


async def test_identify_drops_fact_tag_claims(monkeypatch):
    from PIL import Image

    tag, _fake, _tall, _zone = _shapes()
    added_tag = Shape(shape_id="added-t", image_id="img0", kind=ShapeKind.FACT_TAG, box=_box(10, 10, 50, 30))
    added_prod = Shape(shape_id="added-p", image_id="img0", kind=ShapeKind.PRODUCT, box=_box(200, 200, 300, 400))
    obs = RuleObservation(
        image_id="img0", target_id="z0", kind="illumination", value="on", assessed=True, source=ObservationSource.LLM
    )

    async def fake_identify(image, perception, ctx):
        return IdentificationResult(
            image_id="img0",
            identifications=[Identification(shape_id="t"), Identification(shape_id="img0:r0:s1")],
            added=[added_tag, added_prod],
            rule_observations=[obs],
        )

    monkeypatch.setattr(backlit_module, "identify_image", fake_identify)
    handler = _handler()
    perception = PerceptionResult(image_id="img0", image_size=(800, 600), shapes=[tag])
    result = await handler.identify(Image.new("RGB", (800, 600)), perception, _ctx())
    assert [i.shape_id for i in result.identifications] == ["img0:r0:s1"]
    assert [s.shape_id for s in result.added] == ["added-p"]
    assert result.rule_observations == [obs]


def _header_perception() -> PerceptionResult:
    zone = Shape(
        shape_id="z0",
        image_id="img0",
        kind=ShapeKind.ZONE,
        box=_box(0, 0, 800, 120),
        membership=FixtureMembership.ON_FIXTURE,
    )
    slot = Slot(slot_id="img0:r0:s1", image_id="img0", row_index=0, slot_index=1, box=_box(50, 300, 200, 450))
    return PerceptionResult(image_id="img0", image_size=(800, 600), zones=[zone], slots=[slot], row_count=1)


async def _compare_header(assessed: bool):
    definition = load_slots_definition(_definition_dict())
    ctx = _ctx(
        vision=_RaisingVision(),
        definition=definition,
        bindings=[RuleBinding(rule_id="ill", kind="illumination", target_id="header_light", params={"required": "on"})],
    )
    observation = RuleObservation(
        image_id="img0",
        target_id="z0",
        kind="illumination",
        value="off" if assessed else None,
        assessed=assessed,
        source=ObservationSource.LLM,
    )
    ident = IdentificationResult(image_id="img0", rule_observations=[observation])
    return await _handler().compare([_header_perception()], [ident], ctx)


def _illumination_outcome(result):
    return next(o for shelf in result.shelf_scores for o in shelf.rule_results if o.rule_id == "ill")


async def test_compare_header_rules_from_evidence_only():
    off = await _compare_header(True)
    assert off.overall_compliant is False
    outcome = _illumination_outcome(off)
    assert outcome.assessed is True and outcome.passed is False
    unknown = _illumination_outcome(await _compare_header(False))
    assert unknown.assessed is False and unknown.passed is None


async def test_offline_full_run_reports_measured_result(fake_vision_client, synthetic_shelf_image, offline):
    result = await PlanogramCompliance(
        planogram_config=PlanogramConfig(
            planogram_type="endcap_backlit_multitier",
            planogram_config={
                "rule_bindings": [
                    {"rule_id": "present", "kind": "zone_present", "target_id": "header_light"},
                    {
                        "rule_id": "ill",
                        "kind": "illumination",
                        "target_id": "header_light",
                        "params": {"required": "on"},
                    },
                ]
            },
            slots_definition=_definition_dict(),
        ),
        llm=fake_vision_client,
    ).run(synthetic_shelf_image)
    assert {
        "step3_compliance_results",
        "compliance_results",
        "overall_compliance_score",
        "overall_compliant",
        "identified_products",
        "shelf_regions",
        "rendered_image",
        "overlay_path",
    } <= set(result)
    assert result["compliance_results"] is result["step3_compliance_results"]
    assert result["assessment_status"] != "legacy_unmeasured"
    assert result["overall_compliant"] is False
