"""ProductCounter shared-cycle tests for facings, zones, and configured weights (FEAT-612)."""

from __future__ import annotations

import inspect
import logging
from unittest.mock import MagicMock

from PIL import Image

from parrot.models.detections import AisleConfig, DetectionBox, PlanogramDescription, ShelfConfig
from parrot_pipelines.planogram.comparison.definition import RuleBinding, load_slots_definition
from parrot_pipelines.planogram.contracts import (
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FixtureMembership,
    Identification,
    IdentificationResult,
    ObservationSource,
    PerceptionResult,
    RuleObservation,
    Shape,
    ShapeKind,
    Slot,
)
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types import product_counter as counter_module
from parrot_pipelines.planogram.types.product_counter import ProductCounter


class _RaisingVision:
    """Fails if deterministic comparison accesses a provider."""

    def __getattr__(self, name):
        raise AssertionError(f"compare touched vision.{name}")


def _definition(n_facings: int = 2) -> dict:
    """Return one counter shelf with product facings, required background and optional info zone."""
    return {
        "version": "1",
        "shelves": [
            {
                "shelf_id": "counter",
                "shelf_number": 1,
                "level": "counter",
                "facings": [
                    {
                        "facing_id": f"counter_facing_{slot}",
                        "shelf_id": "counter",
                        "slot": slot,
                        "product": "A",
                        "brand": "Acme",
                        "descriptors": {"display_name": "Counter product A", "identifiers": ["A"]},
                    }
                    for slot in range(1, n_facings + 1)
                ],
            }
        ],
        "zones": [
            {"zone_id": "background", "kind": "advertisement", "shelf_id": "counter", "required": True},
            {"zone_id": "info", "kind": "information_label", "shelf_id": "counter", "required": False},
        ],
    }


def _handler(description: PlanogramDescription | None = None) -> ProductCounter:
    """Create a ProductCounter with a concrete description for shared scoring."""
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.product_counter")
    config = MagicMock()
    config.planogram_config = {}
    config.get_planogram_description.return_value = description or PlanogramDescription(
        brand="Acme", category="counter", aisle=AisleConfig(name="counter"), shelves=[]
    )
    return ProductCounter(pipeline, config)


def _ctx(definition: dict, bindings: list[RuleBinding] | None = None) -> CycleContext:
    """Create a deterministic cycle context."""
    return CycleContext(
        vision=_RaisingVision(),
        definition=load_slots_definition(definition),
        bindings=bindings or [],
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
    )


def _evidence(observed: int) -> tuple[PerceptionResult, IdentificationResult]:
    """Return matching product-slot evidence plus one visible background zone."""
    shapes = []
    slots = []
    identifications = []
    for index in range(observed):
        box = DetectionBox(x1=20 + index * 100, y1=100, x2=100 + index * 100, y2=300, confidence=0.9)
        shapes.append(
            Shape(
                shape_id=f"product_{index}",
                image_id="img0",
                kind=ShapeKind.PRODUCT,
                box=box,
                membership=FixtureMembership.ON_FIXTURE,
            )
        )
        slots.append(
            Slot(
                slot_id=f"img0:r0:s{index + 1}",
                image_id="img0",
                row_index=0,
                slot_index=index + 1,
                box=box,
                anchor_shape_id=f"product_{index}",
            )
        )
        identifications.append(
            Identification(
                shape_id=f"img0:r0:s{index + 1}", image_id="img0", product="A", brand="Acme", occupancy="occupied"
            )
        )
    background = Shape(
        shape_id="background_shape",
        image_id="img0",
        kind=ShapeKind.ZONE,
        box=DetectionBox(x1=0, y1=0, x2=400, y2=80, confidence=0.9),
        membership=FixtureMembership.ON_FIXTURE,
    )
    return (
        PerceptionResult(
            image_id="img0", image_size=(400, 400), shapes=[*shapes, background], slots=slots, zones=[background], row_count=1
        ),
        IdentificationResult(
            image_id="img0",
            identifications=identifications,
            rule_observations=[
                RuleObservation(
                    image_id="img0",
                    target_id="img0:zone-region:background",
                    kind="zone_present",
                    value=True,
                    assessed=True,
                    source=ObservationSource.LLM,
                )
            ],
        ),
    )


def test_default_layout_profile_body_and_zones():
    """Profiles are fresh and contain one product candidate plus zones."""
    first, second = ProductCounter.default_layout_profile(), ProductCounter.default_layout_profile()
    kinds = [profile.kind for profile in first.shape_profiles]
    assert first is not second and first.shape_profiles[0] is not second.shape_profiles[0]
    assert kinds.count("product") == 1 and "zone" in kinds and "fact_tag" not in kinds
    assert first.required_descriptor_fields == [] and first.min_usable_shapes == 1


def test_no_fixed_element_list_or_weights():
    """Expected elements and weights belong to the shared definition/scoring paths."""
    source = inspect.getsource(counter_module)
    for literal in ("_DEFAULT_WEIGHTS", "_EXPECTED_ELEMENTS", "promotional_background", 'get("scoring_weights"', "check_planogram_compliance"):
        assert literal not in source
    for name in ("compute_roi", "detect_objects_roi", "detect_objects"):
        assert name not in ProductCounter.__dict__


async def test_hooks_delegate_to_shared_stages(monkeypatch):
    """Perceive, identify and compare forward their exact cycle inputs."""
    image = Image.new("RGB", (10, 10))
    ctx = CycleContext()
    perception = PerceptionResult(image_id="img0")
    identification = IdentificationResult(image_id="img0")
    comparison = counter_module.ComparisonResult()
    calls = []

    async def fake_perceive(received_image, image_id, received_ctx):
        calls.append(("perceive", received_image, image_id, received_ctx))
        return perception

    async def fake_identify(received_image, received_perception, received_ctx):
        calls.append(("identify", received_image, received_perception, received_ctx))
        return identification

    def fake_compare(perceptions, identifications, received_ctx, description):
        calls.append(("compare", perceptions, identifications, received_ctx, description))
        return comparison

    monkeypatch.setattr(counter_module, "perceive_image", fake_perceive)
    monkeypatch.setattr(counter_module, "identify_image", fake_identify)
    monkeypatch.setattr(counter_module, "compare_observations", fake_compare)
    handler = _handler()
    assert await handler.perceive(image, "img0", ctx) is perception
    assert await handler.identify(image, perception, ctx) is identification
    assert await handler.compare([perception], [identification], ctx) is comparison
    assert [call[0] for call in calls] == ["perceive", "identify", "compare"]
    assert calls[0][1:] == (image, "img0", ctx)
    assert calls[1][1:] == (image, perception, ctx)
    assert calls[2][1:4] == ([perception], [identification], ctx)


async def test_facings_zones_and_optional_info_label():
    """Visible facings/background pass; absent optional info has no mandatory failure or provider access."""
    background = RuleBinding(rule_id="background_present", kind="zone_present", target_id="background")
    perception, identification = _evidence(2)
    result = await _handler().compare([perception], [identification], _ctx(_definition(2), [background]))
    assert result.overall_compliant is True and result.detected_products == 2
    assert not any(outcome.rule_id == "info" for score in result.shelf_scores for outcome in score.rule_results)


async def test_fewer_products_than_facings_stays_in_denominator():
    """An unseen expected facing remains part of the denominator."""
    background = RuleBinding(rule_id="background_present", kind="zone_present", target_id="background")
    perception, identification = _evidence(2)
    result = await _handler().compare([perception], [identification], _ctx(_definition(3), [background]))
    assert result.overall_compliance_score < 1.0 and len(result.position_results) == 3


async def test_configured_weights_change_score():
    """Level-matched ShelfConfig weights alter the same partial shared comparison."""
    text = RuleBinding(
        rule_id="text",
        kind="text_requirements",
        target_id="counter",
        params={"requirements": [{"required_text": "missing"}]},
    )
    perception, identification = _evidence(1)

    def description(product_weight: float, text_weight: float) -> PlanogramDescription:
        return PlanogramDescription(
            brand="Acme",
            category="counter",
            aisle=AisleConfig(name="counter"),
            shelves=[ShelfConfig(level="counter", products=[], product_weight=product_weight, text_weight=text_weight)],
        )

    product_heavy = await _handler(description(0.9, 0.1)).compare(
        [perception], [identification], _ctx(_definition(2), [text])
    )
    text_heavy = await _handler(description(0.5, 0.5)).compare(
        [perception], [identification], _ctx(_definition(2), [text])
    )
    assert product_heavy.overall_compliance_score != text_heavy.overall_compliance_score


def test_type_registered():
    """Existing plan registration resolves the migrated type."""
    assert PlanogramCompliance._PLANOGRAM_TYPES["product_counter"] is ProductCounter
