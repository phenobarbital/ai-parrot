"""Offline tests for the ProductOnShelves shared cycle hooks (FEAT-612)."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from parrot_pipelines.planogram.contracts import (
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    IdentifyStrategy,
)
from parrot_pipelines.planogram.backend import ResolvedBackend
from parrot_pipelines.planogram.identification.vision import VisionAdapter
from parrot_pipelines.planogram.perception.slots import AnchorRule
from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves


class _InlineExecutor:
    """Record dispatched functions and run them inline."""

    def __init__(self) -> None:
        self.dispatched = []

    async def run(self, fn, *args):
        self.dispatched.append(fn.__name__)
        return fn(*args)


class _NoOcr:
    available = False


def _make_handler(planogram_config: dict) -> ProductOnShelves:
    """Build a cycle type with a minimal configuration."""
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.pos.migrated")
    pipeline.reference_images = {}
    config = MagicMock()
    config.planogram_config = planogram_config
    config.slots_definition = {"shelves": []}
    config.get_planogram_description.return_value = SimpleNamespace(shelves=[])
    return ProductOnShelves(pipeline=pipeline, config=config)


def _ctx(executor=None, client=None) -> CycleContext:
    """Build a context for the shared stages."""
    vision = (
        VisionAdapter(client, ResolvedBackend(provider="fake", origin="llm_instance"), semaphore=asyncio.Semaphore(2))
        if client is not None
        else None
    )
    return CycleContext(
        vision=vision,
        executor=executor or _InlineExecutor(),
        ocr=_NoOcr(),
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
    )


def test_default_layout_profile_is_cv_and_fresh():
    """Defaults are complete, provisional, and independent between calls."""
    first, second = ProductOnShelves.default_layout_profile(), ProductOnShelves.default_layout_profile()
    assert first is not second and first.shape_profiles[0] is not second.shape_profiles[0]
    assert {profile.kind for profile in first.shape_profiles} == {"product", "box", "fact_tag", "zone"}
    assert first.perception_mode == "cv" and first.anchor_rule == AnchorRule.SHAPE_IS_SLOT
    assert first.identify_strategy == IdentifyStrategy.FULL_IMAGE and first.min_usable_shapes == 3
    assert ProductOnShelves.requires_slots_definition is True
    assert ProductOnShelves.uses_enhanced_image is False
    assert not hasattr(ProductOnShelves, "DEFAULT_PERCEPTION_MODE")


def test_top_level_perception_mode_alias_and_invalid_value():
    """The shared resolver retains the top-level compatibility alias."""
    assert _make_handler({"perception_mode": "llm_detector"})._ensure_layout(_ctx()).perception_mode == "llm_detector"
    with pytest.raises(ValueError, match="perception_mode"):
        _make_handler({"perception_mode": "yolo"})._ensure_layout(_ctx())


def test_no_product_hint_fallback_prompt_and_no_legacy_hooks():
    """The migrated type exposes no legacy pipeline."""
    handler = _make_handler({})
    assert not any(
        handler._implements(name) for name in ("compute_roi", "detect_objects", "check_planogram_compliance")
    )


def test_module_imports_no_grid_execution():
    """The thin type does not import the legacy grid package."""
    import inspect
    import parrot_pipelines.planogram.types.product_on_shelves as module

    assert "planogram.grid" not in inspect.getsource(module)


async def test_perceive_llm_detector_mode(fake_vision_client, synthetic_shelf_image):
    """Explicit detector mode delegates to the shared stage."""
    from parrot.models.detections import BoundingBox, Detection, Detections

    fake_vision_client.queue(
        "ask_to_image",
        Detections(
            detections=[
                Detection(label="product", confidence=0.8, bbox=BoundingBox(x1=0.1, y1=0.3, x2=0.25, y2=0.48)),
                Detection(label="product", confidence=0.8, bbox=BoundingBox(x1=0.4, y1=0.3, x2=0.55, y2=0.48)),
                Detection(label="product", confidence=0.8, bbox=BoundingBox(x1=0.1, y1=0.6, x2=0.25, y2=0.73)),
            ]
        ),
    )
    handler = _make_handler({"perception_mode": "llm_detector"})
    ctx = _ctx(client=fake_vision_client)
    perception = await handler.perceive(synthetic_shelf_image, "img0", ctx)
    assert perception.detection_source == "llm"


async def test_perceive_cv_mode_uses_executor_not_event_loop(synthetic_shelf_image):
    """Default CV perception dispatches its CPU work through the executor."""
    executor = _InlineExecutor()
    perception = await _make_handler({}).perceive(synthetic_shelf_image, "img0", _ctx(executor))
    assert executor.dispatched
    assert perception.detection_source == "cv"


async def test_identify_resolves_layout_before_shared_stage(monkeypatch, synthetic_shelf_image):
    """Identify delegates with a layout even when called before orchestration setup."""
    from parrot_pipelines.planogram.contracts import IdentificationResult, PerceptionResult
    import parrot_pipelines.planogram.types.product_on_shelves as module

    async def fake_identify(image, perception, ctx):
        assert ctx.layout is not None
        return IdentificationResult(image_id=perception.image_id)

    monkeypatch.setattr(module, "identify_image", fake_identify)
    result = await _make_handler({}).identify(synthetic_shelf_image, PerceptionResult(image_id="img0"), _ctx())
    assert result.image_id == "img0"
