"""Offline tests for the ProductOnShelves perceive/identify hooks."""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from parrot.models.detections import BoundingBox, Detection, Detections
from parrot_pipelines.planogram.comparison.definition import load_slots_definition
from parrot_pipelines.planogram.contracts import (
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    FixtureMembership,
    Identification,
    IdentificationResponse,
    ShapeKind,
)
from parrot_pipelines.planogram.identification.vision import VisionAdapter
from parrot_pipelines.planogram.backend import ResolvedBackend
from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves


class _InlineExecutor:
    """Records dispatched functions and runs them inline (no process pool in tests)."""

    def __init__(self) -> None:
        self.dispatched = []

    async def run(self, fn, *args):
        self.dispatched.append(fn.__name__)
        return fn(*args)

    async def aclose(self) -> None:
        return None


class _NoOcr:
    available = False


def _make_handler(planogram_config: dict) -> ProductOnShelves:
    """Build the type with a MagicMock pipeline and a minimal config."""
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.pos.migrated")
    pipeline.reference_images = {}
    config = MagicMock()
    config.planogram_config = planogram_config
    # Until the compare hook lands (TASK-3446) the type still validates as legacy-only and needs both prompts
    # at construction; the hook under test reads object_identification_prompt=None afterwards.
    config.object_identification_prompt = "objects"
    config.roi_detection_prompt = "roi"
    config.slots_definition = {"shelves": []}
    shelves = [
        SimpleNamespace(products=[SimpleNamespace(name="RR-60"), SimpleNamespace(name="ES-400")]),
        SimpleNamespace(products=[SimpleNamespace(name="DS-770")]),
    ]
    config.get_planogram_description.return_value = SimpleNamespace(shelves=shelves)
    handler = ProductOnShelves(pipeline=pipeline, config=config)
    config.object_identification_prompt = None
    return handler


def _ctx(client=None, executor=None, definition=None) -> CycleContext:
    import asyncio

    vision = (
        VisionAdapter(client, ResolvedBackend(provider="fake", origin="llm_instance"), semaphore=asyncio.Semaphore(2))
        if client is not None
        else None
    )
    return CycleContext(
        vision=vision,
        executor=executor or _InlineExecutor(),
        ocr=_NoOcr(),
        definition=definition,
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
    )


def test_default_perception_mode_is_llm_detector():
    assert ProductOnShelves.DEFAULT_PERCEPTION_MODE == "llm_detector"
    assert ProductOnShelves.requires_slots_definition is True
    assert ProductOnShelves.min_usable_shapes == 3 and ProductOnShelves.uses_enhanced_image is False
    assert _make_handler({})._perception_mode() == "llm_detector"
    assert _make_handler({"perception_mode": "cv"})._perception_mode() == "cv"


def test_invalid_perception_mode_raises():
    handler = _make_handler({"perception_mode": "yolo"})
    with pytest.raises(ValueError, match="perception_mode"):
        handler._perception_mode()


def test_fallback_prompt_is_deterministic_and_lists_hints():
    """Two calls return the same text; product names appear sorted."""
    handler = _make_handler({})
    first = handler.fallback_detection_prompt()
    assert first == handler.fallback_detection_prompt()
    assert "Prefer the following product names if they match: DS-770, ES-400, RR-60" in first
    assert "zone" in first and "0..1" in first


def test_shape_profiles_cover_four_kinds():
    kinds = {p.kind for p in _make_handler({}).get_shape_profiles()}
    assert kinds == {"product", "box", "fact_tag", "zone"}


async def test_perceive_llm_detector_mode(fake_vision_client, synthetic_shelf_image):
    """detection_source == 'llm'; zones excluded from slots; membership assigned."""
    detections = Detections(
        detections=[
            Detection(label="zone", confidence=0.9, bbox=BoundingBox(x1=0.05, y1=0.0, x2=0.95, y2=0.2)),
            Detection(label="product", confidence=0.8, bbox=BoundingBox(x1=0.1, y1=0.3, x2=0.25, y2=0.48)),
            Detection(label="product", confidence=0.8, bbox=BoundingBox(x1=0.4, y1=0.3, x2=0.55, y2=0.48)),
            Detection(label="product", confidence=0.8, bbox=BoundingBox(x1=0.1, y1=0.6, x2=0.25, y2=0.73)),
        ]
    )
    fake_vision_client.queue("ask_to_image", detections)
    handler = _make_handler({})
    enhance = MagicMock()
    handler.pipeline._enhance_image = enhance
    perception = await handler.perceive(synthetic_shelf_image, "img0", _ctx(fake_vision_client))
    assert perception.detection_source == "llm" and perception.ocr_available is False
    assert [z.kind for z in perception.zones] == [ShapeKind.ZONE]
    zone_ids = {z.shape_id for z in perception.zones}
    assert not any(s.anchor_shape_id in zone_ids for s in perception.slots)
    assert len(perception.slots) == 3 and perception.row_count == 2
    assert all(s.membership == FixtureMembership.ON_FIXTURE for s in perception.shapes)
    assert {s.anchor_shape_id for s in perception.slots} == {s.shape_id for s in perception.shapes}
    enhance.assert_not_called()


async def test_perceive_cv_mode_uses_executor_not_event_loop(synthetic_shelf_image):
    """propose_shapes is dispatched through ctx.executor.run; detection_source == 'cv'."""
    executor = _InlineExecutor()
    perception = await _make_handler({"perception_mode": "cv"}).perceive(
        synthetic_shelf_image, "img0", _ctx(executor=executor)
    )
    assert "propose_shapes" in executor.dispatched and "detect_shelf_edges" in executor.dispatched
    assert perception.detection_source == "cv"
    assert all(z.kind == ShapeKind.ZONE for z in perception.zones)


async def test_identify_makes_one_full_image_call(fake_vision_client, synthetic_shelf_image):
    """Exactly one ask_to_image call is recorded on the fake client."""
    handler = _make_handler({})
    detections = Detections(
        detections=[Detection(label="product", confidence=0.8, bbox=BoundingBox(x1=0.1, y1=0.3, x2=0.25, y2=0.48))]
    )
    fake_vision_client.queue("ask_to_image", detections)
    ctx = _ctx(fake_vision_client)
    perception = await handler.perceive(synthetic_shelf_image, "img0", ctx)
    slot_id = perception.slots[0].slot_id
    fake_vision_client.queue(
        "ask_to_image",
        IdentificationResponse(
            existing_identifications=[Identification(shape_id=slot_id, product="ES-400", evidence=["read"])]
        ),
    )
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
                            "product": "ES-400",
                            "descriptors": {"display_name": "ES-400", "family": "ES"},
                        }
                    ],
                }
            ]
        }
    )
    before = len(fake_vision_client.calls_to("ask_to_image"))
    result = await handler.identify(synthetic_shelf_image, perception, _ctx(fake_vision_client, definition=definition))
    assert len(fake_vision_client.calls_to("ask_to_image")) == before + 1
    assert result.identifications[0].product == "ES-400"
    assert "family" in fake_vision_client.calls_to("ask_to_image")[-1]["prompt"]
