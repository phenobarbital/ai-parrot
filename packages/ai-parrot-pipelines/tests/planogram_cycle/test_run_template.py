"""Offline tests of the PlanogramCompliance.run() template (FEAT-574, Module 15)."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, List, Set
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from parrot.models.compliance import ComplianceResult, ComplianceStatus
from parrot.models.detections import BoundingBox, Detection, Detections, DetectionBox
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram import plan as plan_module
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus,
    ComparisonResult,
    FixtureMembership,
    Identification,
    IdentificationResult,
    PerceptionResult,
    Shape,
    ShapeKind,
)
from parrot_pipelines.planogram.plan import PlanogramCompliance
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType

LEGACY_KEYS = {
    "step3_compliance_results",
    "compliance_results",
    "overall_compliance_score",
    "overall_compliant",
    "identified_products",
    "shelf_regions",
    "rendered_image",
    "overlay_path",
}
ADDITIVE_KEYS = {
    "detections",
    "identifications",
    "position_results",
    "shelf_scores",
    "coverage",
    "definition_coverage",
    "assessment_status",
    "strict_compliance_score",
    "evidence_quality",
    "detection_source",
    "ocr_available",
    "resolved_backend",
    "renders",
    "errors",
}


def _result(status=ComplianceStatus.COMPLIANT, score=1.0) -> ComplianceResult:
    return ComplianceResult(
        shelf_level="top",
        expected_products=["A"],
        found_products=["A"],
        missing_products=[],
        unexpected_products=[],
        compliance_status=status,
        compliance_score=score,
    )


class _StubCycleType(AbstractPlanogramType):
    """Migrated-style stub: records calls, returns canned contract objects."""

    uses_enhanced_image: ClassVar[bool] = False
    min_usable_shapes: ClassVar[int] = 0
    fail_on: ClassVar[Set[str]] = set()
    on_fixture_shapes: ClassVar[int] = 2
    empty_results: ClassVar[bool] = False
    perceive_delay: ClassVar[float] = 0.0
    seen_ids: ClassVar[List[str]] = []

    async def perceive(self, image, image_id, ctx):
        type(self).seen_ids.append(image_id)
        if self.perceive_delay:
            await asyncio.sleep(self.perceive_delay)
        if image_id in self.fail_on:
            raise RuntimeError(f"cannot perceive {image_id}")
        shapes = [
            Shape(
                shape_id=f"{image_id}:s{n}",
                image_id=image_id,
                kind=ShapeKind.PRODUCT,
                box=DetectionBox(x1=10 + 60 * n, y1=10, x2=60 + 60 * n, y2=80, confidence=0.9),
                membership=FixtureMembership.ON_FIXTURE,
            )
            for n in range(self.on_fixture_shapes)
        ]
        shapes.append(
            Shape(
                shape_id=f"{image_id}:off",
                image_id=image_id,
                kind=ShapeKind.PRODUCT,
                box=DetectionBox(x1=700, y1=10, x2=790, y2=80, confidence=0.9),
                membership=FixtureMembership.OFF_FIXTURE,
            )
        )
        return PerceptionResult(image_id=image_id, image_size=image.size, shapes=shapes, detection_source="cv")

    async def identify(self, image, perception, ctx):
        idents = [
            Identification(shape_id=s.shape_id, image_id=perception.image_id, product="A", evidence=["x"])
            for s in perception.shapes
        ]
        return IdentificationResult(image_id=perception.image_id, identifications=idents)

    async def compare(self, perceptions, identifications, ctx):
        if self.empty_results:
            return ComparisonResult(overall_compliant=True, assessment_status=AssessmentStatus.COMPLETE)
        return ComparisonResult(
            compliance_results=[_result()],
            overall_compliance_score=1.0,
            overall_compliant=True,
            assessment_status=AssessmentStatus.COMPLETE,
        )


class _InlineExecutor:
    """CpuExecutor stand-in: runs CPU helpers inline (worktree sources lack the compiled Cython extensions
    a spawned worker would need; the real executor is covered by test_cpu_executor.py)."""

    def __init__(self, max_workers: int = 2) -> None:
        self.max_workers = max_workers

    async def run(self, fn, *args):
        return fn(*args)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def inline_executor(monkeypatch):
    monkeypatch.setattr(plan_module, "CpuExecutor", _InlineExecutor)


@pytest.fixture
def pipeline(monkeypatch, fake_vision_client):
    """PlanogramCompliance wired to the stub type and the fake client."""
    monkeypatch.setitem(PlanogramCompliance._PLANOGRAM_TYPES, "stub_cycle", _StubCycleType)
    for name, value in (
        ("fail_on", set()),
        ("min_usable_shapes", 0),
        ("on_fixture_shapes", 2),
        ("empty_results", False),
        ("perceive_delay", 0.0),
        ("seen_ids", []),
    ):
        monkeypatch.setattr(_StubCycleType, name, value)
    config = PlanogramConfig(planogram_type="stub_cycle", planogram_config={})
    return PlanogramCompliance(planogram_config=config, llm=fake_vision_client)


async def test_run_single_image_returns_legacy_and_additive_keys(pipeline, synthetic_shelf_image):
    result = await pipeline.run(synthetic_shelf_image)
    assert LEGACY_KEYS | ADDITIVE_KEYS <= set(result)
    assert result["compliance_results"] is result["step3_compliance_results"]
    assert result["overall_compliant"] is True and result["overall_compliance_score"] == 1.0
    assert result["detection_source"] == "cv"
    assert result["resolved_backend"] == "fake"
    assert len(result["renders"]) == 1 and isinstance(result["rendered_image"], Image.Image)
    assert [p.product_model for p in result["identified_products"]] == ["A", "A", "A"]


@pytest.mark.parametrize("ptype", sorted(PlanogramCompliance._PLANOGRAM_TYPES))
async def test_run_preserves_eight_keys_for_every_type(
    ptype, fake_vision_client, synthetic_shelf_image, inline_executor
):
    """Every registered type keeps the eight legacy keys through the new template (type work stubbed)."""
    cls = PlanogramCompliance._PLANOGRAM_TYPES[ptype]
    definition = {
        "shelves": [
            {
                "shelf_id": "shelf_1",
                "shelf_number": 1,
                "facings": [
                    {
                        "facing_id": "f1",
                        "shelf_id": "shelf_1",
                        "slot": 1,
                        "product": "A",
                        "descriptors": {"display_name": "A"},
                    }
                ],
            }
        ]
    }
    config = PlanogramConfig(
        planogram_type=ptype,
        planogram_config={"brand": "X", "category": "Y", "aisle": {"name": "a"}, "shelves": []},
        roi_detection_prompt="roi",
        object_identification_prompt="objects",
        slots_definition=definition if cls.requires_slots_definition else None,
    )
    pipe = PlanogramCompliance(planogram_config=config, llm=fake_vision_client)
    handler = pipe._type_handler
    migrated = handler._implements("perceive")
    if migrated:
        handler.perceive = AsyncMock(
            return_value=PerceptionResult(image_id="img0", image_size=synthetic_shelf_image.size, detection_source="cv")
        )
        handler.identify = AsyncMock(return_value=IdentificationResult(image_id="img0"))
        handler.compare = AsyncMock(
            return_value=ComparisonResult(
                compliance_results=[_result(ComplianceStatus.NON_COMPLIANT, 0.4)],
                assessment_status=AssessmentStatus.INCONCLUSIVE,
            )
        )
    else:
        handler.compute_roi = AsyncMock(return_value=(None, None, None, None, []))
        handler.detect_objects = AsyncMock(return_value=([], []))
        handler.check_planogram_compliance = MagicMock(return_value=[_result(ComplianceStatus.NON_COMPLIANT, 0.4)])
    result = await pipe.run(synthetic_shelf_image)
    assert LEGACY_KEYS <= set(result)
    assert result["compliance_results"] is result["step3_compliance_results"]
    if migrated:
        assert result["assessment_status"] == AssessmentStatus.INCONCLUSIVE
        assert result["detection_source"] == "cv"
    else:
        assert result["assessment_status"] == AssessmentStatus.LEGACY_UNMEASURED
        assert result["detection_source"] == "legacy_llm"


async def test_run_single_image_keeps_sfx_filename_rule(pipeline, synthetic_shelf_image, tmp_path):
    r1 = await pipeline.run(synthetic_shelf_image, output_dir=tmp_path)
    r2 = await pipeline.run(synthetic_shelf_image, output_dir=tmp_path, image_id="store7")
    assert r1["overlay_path"].endswith("compliance_render.png")
    assert r2["overlay_path"].endswith("compliance_render_store7.png")
    assert _StubCycleType.seen_ids == ["img0", "store7"]  # migrated types always receive a real id


async def test_run_multi_image_renders_and_failures(pipeline, synthetic_shelf_image, tmp_path):
    """Second photo fails: isolated in errors; renders only for successes; singular keys = first success."""
    _StubCycleType.fail_on = {"b"}
    result = await pipeline.run(
        [synthetic_shelf_image, synthetic_shelf_image, synthetic_shelf_image],
        output_dir=tmp_path,
        image_id=["a", "b", "c"],
    )
    assert [r.image_id for r in result["renders"]] == ["a", "c"]
    assert result["overlay_path"].endswith("compliance_render_a.png")
    assert (tmp_path / "compliance_render_c.png").is_file()
    assert any(e.startswith("b:") for e in result["errors"])
    assert LEGACY_KEYS | ADDITIVE_KEYS <= set(result)
    ids = {i["image_id"] for i in result["identifications"]}
    assert ids == {"a", "c"}


async def test_run_default_multi_ids(pipeline, synthetic_shelf_image):
    await pipeline.run([synthetic_shelf_image, synthetic_shelf_image])
    assert _StubCycleType.seen_ids == ["img0", "img1"]


async def test_run_all_images_failed_is_inconclusive(pipeline, synthetic_shelf_image):
    _StubCycleType.fail_on = {"img0"}
    result = await pipeline.run(synthetic_shelf_image)
    assert result["rendered_image"] is None and result["overlay_path"] is None
    assert result["overall_compliant"] is False
    assert result["assessment_status"] == "inconclusive"
    assert result["compliance_results"] == []
    assert result["overall_compliance_score"] == 0.0


async def test_run_image_id_length_mismatch_raises(pipeline, synthetic_shelf_image):
    with pytest.raises(ValueError):
        await pipeline.run([synthetic_shelf_image, synthetic_shelf_image], image_id=["a"])
    with pytest.raises(ValueError):
        await pipeline.run([synthetic_shelf_image, synthetic_shelf_image], image_id=["a", "a"])
    with pytest.raises(ValueError):
        await pipeline.run([])


async def test_run_fallback_sets_detection_source_llm(
    pipeline, synthetic_shelf_image, fake_vision_client, inline_executor
):
    _StubCycleType.min_usable_shapes = 3  # 2 on-fixture (+1 off-fixture that must not count)
    detections = Detections(
        detections=[
            Detection(label="zone", confidence=0.9, bbox=BoundingBox(x1=0.1, y1=0.0, x2=0.9, y2=0.1)),
            Detection(label="product", confidence=0.8, bbox=BoundingBox(x1=0.2, y1=0.3, x2=0.3, y2=0.5)),
            Detection(label="product", confidence=0.8, bbox=BoundingBox(x1=0.4, y1=0.3, x2=0.5, y2=0.5)),
        ]
    )
    fake_vision_client.queue("ask_to_image", detections)
    result = await pipeline.run(synthetic_shelf_image)
    assert result["detection_source"] == "llm"
    perception = result["detections"][0]
    assert perception["slots"] == []
    assert all(s["source"] == "llm" for s in perception["shapes"])
    assert all(s["membership"] == "on_fixture" for s in perception["shapes"])
    assert len(fake_vision_client.calls_to("ask_to_image")) == 1


async def test_run_fallback_not_triggered_at_threshold(pipeline, synthetic_shelf_image, fake_vision_client):
    _StubCycleType.min_usable_shapes = 2
    result = await pipeline.run(synthetic_shelf_image)
    assert result["detection_source"] == "cv"
    assert fake_vision_client.calls_to("ask_to_image") == []


async def test_run_fallback_failure_populates_errors(
    pipeline, synthetic_shelf_image, fake_vision_client, inline_executor
):
    _StubCycleType.min_usable_shapes = 5
    fake_vision_client.queue("ask_to_image", RuntimeError("503"))
    result = await pipeline.run(synthetic_shelf_image)
    assert result["detection_source"] == "cv"  # original perception kept
    assert any("llm_detector" in e for e in result["errors"])
    assert any("fallback produced no shapes" in e for e in result["errors"])


async def test_run_uses_untouched_image_for_migrated_types(pipeline, synthetic_shelf_image, monkeypatch):
    enhance = MagicMock(side_effect=lambda img: img)
    monkeypatch.setattr(pipeline, "_enhance_image", enhance)
    await pipeline.run(synthetic_shelf_image)
    enhance.assert_not_called()


async def test_run_closes_executor_on_cancellation(pipeline, synthetic_shelf_image, monkeypatch):
    closed: List[Any] = []

    class _Recording(plan_module.CpuExecutor):
        async def aclose(self) -> None:
            closed.append(self)
            await super().aclose()

    monkeypatch.setattr(plan_module, "CpuExecutor", _Recording)
    _StubCycleType.perceive_delay = 5.0
    task = asyncio.create_task(pipeline.run(synthetic_shelf_image))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(closed) == 1

    _StubCycleType.perceive_delay = 0.0
    await pipeline.run(synthetic_shelf_image)
    assert len(closed) == 2


async def test_empty_compliance_results_never_compliant(pipeline, synthetic_shelf_image):
    _StubCycleType.empty_results = True
    result = await pipeline.run(synthetic_shelf_image)
    assert result["compliance_results"] == []
    assert result["overall_compliant"] is False


def test_constructor_passes_config_backend(fake_vision_client, monkeypatch):
    monkeypatch.setitem(PlanogramCompliance._PLANOGRAM_TYPES, "stub_cycle", _StubCycleType)
    config = PlanogramConfig(planogram_type="stub_cycle", planogram_config={}, llm_backend="anthropic:claude-x")
    fake_client = MagicMock(client_name="Claude", model="claude-x")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(PlanogramCompliance, "_get_llm", lambda self, provider, model, **kw: fake_client)
        pipe = PlanogramCompliance(planogram_config=config, cpu_workers=3, llm_concurrency=2, llm_timeout=9.0)
    assert pipe.resolved_backend.as_string() == "anthropic:claude-x"
    assert pipe.resolved_backend.origin == "config"
    assert (pipe.cpu_workers, pipe.llm_concurrency, pipe.llm_timeout) == (3, 2, 9.0)


async def test_ocr_is_disabled_by_default_and_can_be_enabled(
    pipeline, synthetic_shelf_image, fake_vision_client, monkeypatch
):
    created = 0

    class _AvailableOcr:
        available = True

        def __init__(self) -> None:
            nonlocal created
            created += 1

    monkeypatch.setattr(plan_module, "OcrReader", _AvailableOcr)

    disabled_result = await pipeline.run(synthetic_shelf_image)
    assert pipeline.enabled_ocr is False
    assert disabled_result["ocr_available"] is False
    assert created == 0

    config = PlanogramConfig(planogram_type="stub_cycle", planogram_config={})
    enabled_pipeline = PlanogramCompliance(planogram_config=config, llm=fake_vision_client, enabled_ocr=True)
    enabled_result = await enabled_pipeline.run(synthetic_shelf_image)
    assert enabled_pipeline.enabled_ocr is True
    assert enabled_result["ocr_available"] is True
    assert created == 1
