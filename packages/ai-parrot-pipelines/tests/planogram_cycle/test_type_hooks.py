"""AbstractPlanogramType cycle hooks, validate_contract and the legacy adapter (TASK-3442)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import MagicMock

import pytest
from PIL import Image

from parrot.models.compliance import ComplianceResult, ComplianceStatus
from parrot.models.detections import DetectionBox, ShelfRegion
from parrot_pipelines.planogram.contracts import (
    AssessmentStatus,
    ComparisonResult,
    CreditPolicy,
    CycleContext,
    EvidenceWeights,
    IdentificationResult,
    LegacyPayload,
    PerceptionResult,
)
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType


def _pipeline():
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.type_hooks")
    pipeline.resolved_backend = MagicMock(provider="google", model=None)
    return pipeline


def _config(**overrides):
    """MagicMock config with a REAL planogram_config dict (a bare MagicMock would enable fact-tag branches)."""
    config = MagicMock()
    config.planogram_config = overrides.pop("planogram_config", {})
    config.config_name = "cfg"
    config.get_planogram_description.return_value = SimpleNamespace(brand="Acme", shelves=[])
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _ctx(tmp_path=None) -> CycleContext:
    return CycleContext(
        vision=None,
        executor=None,
        ocr=None,
        credit_policy=CreditPolicy.default(),
        evidence_weights=EvidenceWeights(),
        output_dir=tmp_path,
    )


def _perception(legacy=True) -> PerceptionResult:
    return PerceptionResult(
        image_id="img0",
        image_size=(64, 64),
        detection_source="legacy_llm",
        legacy=LegacyPayload(identified_products=[], shelf_regions=[]) if legacy else None,
    )


VIRTUAL = ShelfRegion(shelf_id="virtual", level="top", bbox=DetectionBox(x1=0, y1=0, x2=64, y2=64, confidence=1.0))


class _RecordingLegacy(AbstractPlanogramType):
    """Legacy type that records the order in which the adapter calls it."""

    def __init__(self, pipeline, config, results=None, fail_roi=False):
        self.calls = []
        self._results = results if results is not None else []
        self._fail_roi = fail_roi
        super().__init__(pipeline, config)

    async def compute_roi(self, img):
        self.calls.append("compute_roi")
        if self._fail_roi:
            raise RuntimeError("no poster")
        endcap = SimpleNamespace(bbox=SimpleNamespace(x1=0.0, y1=0.0, x2=1.0, y2=1.0))
        panel = SimpleNamespace(content="Hello", confidence=0.7, bbox=SimpleNamespace(x1=0.1, y1=0.1, x2=0.5, y2=0.2))
        brand = SimpleNamespace(label="Acme", confidence=0.8, bbox=SimpleNamespace(x1=0.2, y1=0.0, x2=0.4, y2=0.1))
        return endcap, None, brand, panel, []

    async def detect_objects(self, img, roi, macro_objects):
        self.calls.append("detect_objects")
        return [], []

    def check_planogram_compliance(self, identified_products, planogram_description):
        self.calls.append("check_planogram_compliance")
        return self._results

    def _generate_virtual_shelves(self, bbox, size, description):
        self.calls.append("_generate_virtual_shelves")
        return [VIRTUAL]

    def _refine_shelves_from_fact_tags(self, shelf_regions, identified_products):
        self.calls.append("_refine_shelves_from_fact_tags")
        return shelf_regions

    def _assign_products_to_shelves(self, products, shelves, use_y1_assignment=False):
        self.calls.append(f"_assign_products_to_shelves(y1={use_y1_assignment})")

    async def _ocr_fact_tags(self, products, img, description, shelf_regions=None):
        self.calls.append("_ocr_fact_tags")
        return {}

    def _corroborate_products_with_fact_tags(self, products, shelf_map, description):
        self.calls.append("_corroborate_products_with_fact_tags")


class _CycleOnly(AbstractPlanogramType):
    """Implements the three hooks and none of the legacy methods."""

    async def perceive(self, image, image_id, ctx):
        return _perception(legacy=False)

    async def identify(self, image, perception, ctx):
        return IdentificationResult(image_id="img0")

    async def compare(self, perceptions, identifications, ctx):
        return ComparisonResult()


def test_validate_contract_rejects_incomplete_type():
    class Half(AbstractPlanogramType):
        async def compute_roi(self, img):
            return None, None, None, None, []

    with pytest.raises(TypeError, match="abstract"):
        Half(pipeline=_pipeline(), config=MagicMock())
    with pytest.raises(TypeError, match="abstract"):
        AbstractPlanogramType(pipeline=_pipeline(), config=MagicMock())


def test_cycle_only_type_constructs():
    handler = _CycleOnly(
        pipeline=_pipeline(), config=_config(roi_detection_prompt=None, object_identification_prompt=None)
    )
    assert handler.identify_strategy.value == "full_image"
    assert handler.requires_slots_definition is False and handler.min_usable_shapes == 0
    assert handler.uses_enhanced_image is True


def test_legacy_type_missing_prompts_fails_at_construction():
    with pytest.raises(ValueError, match="roi_detection_prompt"):
        _RecordingLegacy(_pipeline(), _config(roi_detection_prompt=None))
    with pytest.raises(ValueError, match="object_identification_prompt"):
        _RecordingLegacy(_pipeline(), _config(object_identification_prompt=""))
    assert _RecordingLegacy(_pipeline(), MagicMock())  # a MagicMock config passes


def test_type_requiring_slots_definition_fails_without_it():
    class NeedsSlots(_CycleOnly):
        requires_slots_definition: ClassVar[bool] = True

    with pytest.raises(ValueError, match="migration runbook"):
        NeedsSlots(pipeline=_pipeline(), config=_config(slots_definition=None))
    assert NeedsSlots(pipeline=_pipeline(), config=_config(slots_definition={"shelves": []}))


async def test_unimplemented_legacy_method_raises_not_implemented():
    handler = _CycleOnly(pipeline=_pipeline(), config=_config())
    with pytest.raises(NotImplementedError, match="_CycleOnly does not implement the legacy contract"):
        await handler.compute_roi(Image.new("RGB", (4, 4)))
    with pytest.raises(NotImplementedError, match="legacy contract"):
        await handler.detect_objects_roi(Image.new("RGB", (4, 4)), None)
    with pytest.raises(NotImplementedError, match="legacy contract"):
        await handler.detect_objects(Image.new("RGB", (4, 4)), None, None)
    with pytest.raises(NotImplementedError, match="legacy contract"):
        handler.check_planogram_compliance([], None)


async def test_legacy_perceive_order_and_payload(tmp_path):
    handler = _RecordingLegacy(_pipeline(), _config(planogram_config={"use_fact_tag_boundaries": True}))
    result = await handler.perceive(Image.new("RGB", (64, 64)), "img0", _ctx(tmp_path))
    assert handler.calls == [
        "compute_roi",
        "detect_objects",
        "_generate_virtual_shelves",
        "_refine_shelves_from_fact_tags",
        "_assign_products_to_shelves(y1=True)",
        "_ocr_fact_tags",
        "_corroborate_products_with_fact_tags",
    ]
    assert result.detection_source == "legacy_llm" and isinstance(result.legacy, LegacyPayload)
    assert result.legacy.shelf_regions == [VIRTUAL]
    types = [p.product_type for p in result.legacy.identified_products]
    assert types == ["text_overlay", "brand_logo"]  # header injections come last
    assert (tmp_path / "debug_step1_roi_img0.png").is_file()
    assert result.errors == []


async def test_legacy_perceive_survives_compute_roi_failure():
    handler = _RecordingLegacy(_pipeline(), _config(), fail_roi=True)
    result = await handler.perceive(Image.new("RGB", (64, 64)), "img0", _ctx())
    assert handler.calls[:2] == ["compute_roi", "detect_objects"]
    assert "_generate_virtual_shelves" not in handler.calls
    assert result.errors == ["compute_roi failed: no poster"]
    assert result.legacy.identified_products == []


async def test_default_identify_is_passthrough():
    handler = _RecordingLegacy(_pipeline(), _config())
    out = await handler.identify(Image.new("RGB", (4, 4)), _perception(), _ctx())
    assert out.image_id == "img0" and out.identifications == [] and out.added == [] and out.errors == []


async def test_legacy_adapter_empty_results_not_compliant():
    handler = _RecordingLegacy(_pipeline(), _config(), results=[])
    out = await handler.compare([_perception()], [], _ctx())
    assert out.overall_compliant is False and out.overall_compliance_score == 0.0
    assert out.assessment_status == AssessmentStatus.LEGACY_UNMEASURED and out.coverage is None
    assert out.definition_coverage is None and out.strict_compliance_score is None and out.evidence_quality is None

    missing = await handler.compare([_perception(legacy=False)], [], _ctx())
    assert missing.overall_compliant is False and missing.errors


def _result(score, status):
    return ComplianceResult(
        shelf_level="top",
        expected_products=[],
        found_products=[],
        missing_products=[],
        unexpected_products=[],
        compliance_status=status,
        compliance_score=score,
    )


async def test_default_compare_mean_and_all_compliant():
    results = [_result(0.9, ComplianceStatus.COMPLIANT), _result(0.5, ComplianceStatus.NON_COMPLIANT)]
    handler = _RecordingLegacy(_pipeline(), _config(), results=results)
    out = await handler.compare([_perception()], [], _ctx())
    assert out.overall_compliance_score == pytest.approx(0.7)
    assert out.overall_compliant is False
    assert out.compliance_results == results

    all_ok = _RecordingLegacy(_pipeline(), _config(), results=[_result(0.9, ComplianceStatus.COMPLIANT)])
    assert (await all_ok.compare([_perception()], [], _ctx())).overall_compliant is True


def test_fallback_detection_prompt_defaults_to_none():
    assert _RecordingLegacy(_pipeline(), _config()).fallback_detection_prompt() is None
