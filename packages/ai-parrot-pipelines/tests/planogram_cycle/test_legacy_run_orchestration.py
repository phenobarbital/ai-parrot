"""Characterization test: the COMPLETE legacy run() orchestration, observed at the public level (FEAT-574)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from parrot.models.compliance import ComplianceResult, ComplianceStatus
from parrot.models.detections import BoundingBox, Detection, DetectionBox, IdentifiedProduct, ShelfRegion
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram import PlanogramCompliance


def raw_config(**flags: Any) -> Dict[str, Any]:
    """header (promo) + top (two products); ``flags`` e.g. use_fact_tag_boundaries=True."""
    return {
        "brand": "TestBrand",
        "category": "Scanners",
        "aisle": {"name": "Electronics > Test", "lighting_conditions": "normal"},
        "shelves": [
            {
                "level": "header",
                "height_ratio": 0.2,
                "products": [
                    {
                        "name": "TestBrand Backlit",
                        "product_type": "promotional_graphic",
                        "visual_features": ["illuminated logo"],
                        "text_requirements": [{"required_text": "Hello Savings"}],
                    }
                ],
            },
            {
                "level": "top",
                "height_ratio": 0.8,
                "products": [
                    {"name": "ES-400", "product_type": "product"},
                    {"name": "RR-60", "product_type": "product"},
                ],
            },
        ],
        **flags,
    }


def spy(obj: Any, name: str, log: List[str]) -> None:
    """Wrap ``obj.<name>`` (sync or async) so every call appends ``name`` to ``log`` and still runs for real."""
    original = getattr(obj, name)
    if asyncio.iscoroutinefunction(original):

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            log.append(name)
            return await original(*args, **kwargs)

    else:

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            log.append(name)
            return original(*args, **kwargs)

    setattr(obj, name, wrapper)


def roi_stub() -> Tuple[Detection, None, Detection, Detection, list]:
    """(endcap, ad, brand, panel_text, raw_dets) with FRACTIONAL boxes, as _find_poster returns them."""
    endcap = Detection(label="endcap", confidence=0.9, bbox=BoundingBox(x1=0.1, y1=0.0, x2=0.9, y2=1.0))
    brand = Detection(label="TestBrand", confidence=0.8, bbox=BoundingBox(x1=0.4, y1=0.02, x2=0.6, y2=0.08))
    text = Detection(
        label="poster_text",
        confidence=0.7,
        content="  Hello Savings  ",
        bbox=BoundingBox(x1=0.2, y1=0.1, x2=0.8, y2=0.18),
    )
    return endcap, None, brand, text, []


def detected_stub() -> Tuple[List[IdentifiedProduct], List[ShelfRegion]]:
    """A backlit promo on the header + one product, and ONE detector shelf that virtual shelves must replace."""
    promo = IdentifiedProduct(
        product_type="graphic",
        product_model="TestBrand Backlit",
        confidence=0.9,
        detection_box=DetectionBox(x1=100, y1=10, x2=700, y2=190, confidence=0.9),
    )
    es400 = IdentifiedProduct(
        product_type="product",
        product_model="ES-400",
        confidence=0.9,
        detection_box=DetectionBox(x1=120, y1=300, x2=320, y2=700, confidence=0.9),
    )
    detector_shelf = ShelfRegion(
        shelf_id="detector_only",
        level="detector_only",
        bbox=DetectionBox(x1=0, y1=0, x2=800, y2=1000, confidence=1.0),
    )
    return [promo, es400], [detector_shelf]


def build_pipeline(
    fake: Any, log: List[str], stubs: Optional[Dict[str, AsyncMock]] = None, **flags: Any
) -> PlanogramCompliance:
    """Real pipeline + real ProductOnShelves handler; legacy public methods stubbed, everything else spied."""
    cfg = PlanogramConfig(
        config_name="legacy",
        planogram_type="product_on_shelves",
        planogram_config=raw_config(**flags),
        roi_detection_prompt="roi",
        object_identification_prompt="objects",
    )
    with patch("parrot.clients.google.GoogleGenAIClient", MagicMock()):
        pipeline = PlanogramCompliance(planogram_config=cfg, llm=fake)
    pipeline.roi_client = fake  # SAME object as pipeline.llm — refactor-proof
    handler = pipeline._type_handler
    compute_roi = AsyncMock(return_value=roi_stub())
    detect_objects = AsyncMock(return_value=detected_stub())
    handler.compute_roi = compute_roi
    handler.detect_objects = detect_objects
    handler.detect_objects_roi = AsyncMock(return_value=[])
    if stubs is not None:
        stubs.update(compute_roi=compute_roi, detect_objects=detect_objects)
    for name in (
        "compute_roi",
        "detect_objects",
        "_generate_virtual_shelves",
        "_refine_shelves_from_fact_tags",
        "_assign_products_to_shelves",
        "_ocr_fact_tags",
        "_corroborate_products_with_fact_tags",
        "check_planogram_compliance",
    ):
        spy(handler, name, log)
    for name in ("_enhance_image", "render_evaluated_image"):
        spy(pipeline, name, log)
    return pipeline


def assert_subsequence(log: List[str], expected: List[str]) -> None:
    """Every name of ``expected`` appears in ``log`` in that relative order."""
    it = iter(log)
    assert all(name in it for name in expected), f"order broken: {log}"


# --------------------------------------------------------------------------- Part 2: order, promo OCR, injections


async def test_legacy_run_orchestration_order(fake_vision_client, synthetic_shelf_image, tmp_path: Path) -> None:
    """Spec §6 steps 2→19 happen in order; detect_objects_roi is never called."""
    log: List[str] = []
    stubs: Dict[str, AsyncMock] = {}
    pipeline = build_pipeline(fake_vision_client, log, stubs, use_fact_tag_boundaries=True)
    assert pipeline.roi_client is pipeline.llm
    spy(fake_vision_client, "ask_to_image", log)
    await pipeline.run(synthetic_shelf_image, output_dir=tmp_path)
    assert_subsequence(
        log,
        [
            "_enhance_image",
            "compute_roi",
            "detect_objects",
            "ask_to_image",  # promotional OCR
            "_generate_virtual_shelves",
            "_refine_shelves_from_fact_tags",
            "_assign_products_to_shelves",
            "_ocr_fact_tags",
            "_corroborate_products_with_fact_tags",
            "check_planogram_compliance",
            "render_evaluated_image",
        ],
    )
    assert log.count("_enhance_image") == 1  # legacy path works on the ENHANCED image
    pipeline._type_handler.detect_objects_roi.assert_not_called()
    call = stubs["detect_objects"].await_args
    endcap = roi_stub()[0]
    assert call.kwargs["roi"] == endcap
    assert call.kwargs["macro_objects"] is None
    promo_ocr_index = log.index("ask_to_image")
    assert log.index("detect_objects") < promo_ocr_index < log.index("_generate_virtual_shelves")


async def test_legacy_promotional_ocr_enrichment(fake_vision_client, synthetic_shelf_image) -> None:
    """One vision call per promo item, on its crop; answer lines are parsed into the product."""
    fake_vision_client.queue(
        "ask_to_image", "TestBrand EcoTank\nCONFIRMED: illuminated logo\nTEXT_FOUND: Hello Savings"
    )
    log: List[str] = []
    pipeline = build_pipeline(fake_vision_client, log)
    result = await pipeline.run(synthetic_shelf_image)
    promo = next(p for p in result["identified_products"] if p.product_model == "TestBrand Backlit")
    assert promo.product_type == "promotional_graphic"  # forced (was "graphic")
    assert promo.ocr_text == "TestBrand EcoTank"
    assert promo.brand == "TestBrand"  # verified via OCR text
    for feature in ("ocr:TestBrand EcoTank", "TestBrand EcoTank", "illuminated logo", "Hello Savings"):
        assert feature in promo.visual_features
    calls = fake_vision_client.calls_to("ask_to_image")
    assert len(calls) == 1  # non-promo products trigger no call
    call = calls[0]
    assert call["image_size"] == (600, 180)  # the promo's detection_box crop
    assert call["kwargs"]["no_memory"] is True and call["kwargs"]["max_tokens"] == 1024  # never assert "model"
    assert "- illuminated logo" in call["prompt"]
    assert '- "Hello Savings"' in call["prompt"]


async def test_legacy_promo_ocr_failure_is_swallowed(fake_vision_client, synthetic_shelf_image) -> None:
    """A failing promo OCR call is logged; the run completes and the product keeps its original type."""
    fake_vision_client.queue("ask_to_image", RuntimeError("503"))
    pipeline = build_pipeline(fake_vision_client, [])
    result = await pipeline.run(synthetic_shelf_image)
    promo = next(p for p in result["identified_products"] if p.product_model == "TestBrand Backlit")
    assert promo.product_type == "graphic"


async def test_legacy_virtual_shelves_replace_detector_shelves(fake_vision_client, synthetic_shelf_image) -> None:
    """With an endcap ROI the virtual shelves REPLACE whatever detect_objects returned."""
    pipeline = build_pipeline(fake_vision_client, [])
    result = await pipeline.run(synthetic_shelf_image)
    levels = [s.level for s in result["shelf_regions"]]
    assert "detector_only" not in levels
    assert levels == ["header", "top"]
    es400 = next(p for p in result["identified_products"] if p.product_model == "ES-400")
    assert es400.shelf_location == "top"


async def test_legacy_poster_text_and_brand_logo_injection(fake_vision_client, synthetic_shelf_image) -> None:
    """panel_text and brand detections become synthetic header products BEFORE compliance runs."""
    seen: List[List[str]] = []
    pipeline = build_pipeline(fake_vision_client, [])
    original = pipeline._type_handler.check_planogram_compliance

    def capture(products: List[IdentifiedProduct], description: Any) -> List[ComplianceResult]:
        seen.append([p.product_type for p in products])
        return original(products, description)

    pipeline._type_handler.check_planogram_compliance = capture
    result = await pipeline.run(synthetic_shelf_image)
    assert "text_overlay" in seen[0] and "brand_logo" in seen[0]
    text = next(p for p in result["identified_products"] if p.product_type == "text_overlay")
    assert (text.product_model, text.shelf_location, text.visual_features) == (
        "poster_text",
        "header",
        ["ocr:Hello Savings"],
    )
    tb = text.detection_box
    assert (tb.x1, tb.y1, tb.x2, tb.y2) == (160, 100, 640, 180)
    # Observed: the stripped text is stored on the DetectionBox, not on the product (product ocr_text stays None).
    assert tb.ocr_text == "Hello Savings"
    assert text.ocr_text is None
    assert text.confidence == pytest.approx(0.7)

    logo = next(p for p in result["identified_products"] if p.product_type == "brand_logo")
    assert (logo.product_model, logo.brand, logo.shelf_location) == ("TestBrand", "TestBrand", "header")
    lb = logo.detection_box
    assert (lb.x1, lb.y1, lb.x2, lb.y2) == (320, 20, 480, 80)
    assert logo.confidence == pytest.approx(0.8)


# --------------------------------------------------------------------------- Part 3: gating, failure, aggregation


async def test_legacy_fact_tag_steps_are_gated_by_config_flag(fake_vision_client, synthetic_shelf_image) -> None:
    """Without use_fact_tag_boundaries: no refine, no fact-tag OCR, no corroboration, use_y1_assignment False."""
    y1_flags: List[bool] = []

    def capture_y1(pipeline: PlanogramCompliance) -> None:
        wrapped = pipeline._type_handler._assign_products_to_shelves

        def recorder(*args: Any, **kwargs: Any) -> Any:
            y1_flags.append(kwargs.get("use_y1_assignment"))
            return wrapped(*args, **kwargs)

        pipeline._type_handler._assign_products_to_shelves = recorder

    log: List[str] = []
    pipeline = build_pipeline(fake_vision_client, log)
    capture_y1(pipeline)
    await pipeline.run(synthetic_shelf_image)
    for name in ("_refine_shelves_from_fact_tags", "_ocr_fact_tags", "_corroborate_products_with_fact_tags"):
        assert name not in log
    assert "_assign_products_to_shelves" in log

    flagged_log: List[str] = []
    flagged = build_pipeline(fake_vision_client, flagged_log, use_fact_tag_boundaries=True)
    capture_y1(flagged)
    await flagged.run(synthetic_shelf_image)
    assert y1_flags == [False, True]


async def test_legacy_compute_roi_failure_is_swallowed(fake_vision_client, synthetic_shelf_image) -> None:
    """compute_roi raising is only logged: detection still runs with roi=None and no virtual shelves are built."""
    log: List[str] = []
    stubs: Dict[str, AsyncMock] = {}
    pipeline = build_pipeline(fake_vision_client, log, stubs)
    pipeline._type_handler.compute_roi = AsyncMock(side_effect=RuntimeError("no poster"))
    result = await pipeline.run(synthetic_shelf_image)
    assert "_generate_virtual_shelves" not in log
    assert [s.level for s in result["shelf_regions"]] == ["detector_only"]
    assert stubs["detect_objects"].await_args.kwargs["roi"] is None
    types = {p.product_type for p in result["identified_products"]}
    assert "text_overlay" not in types and "brand_logo" not in types


def _shelf_result(level: str, status: ComplianceStatus, score: float) -> ComplianceResult:
    """A canned per-shelf result."""
    return ComplianceResult(
        shelf_level=level,
        expected_products=[],
        found_products=[],
        missing_products=[],
        unexpected_products=[],
        compliance_status=status,
        compliance_score=score,
    )


async def test_legacy_overall_aggregation(fake_vision_client, synthetic_shelf_image) -> None:
    """overall score = unweighted mean of shelf scores; overall_compliant = every shelf COMPLIANT (no threshold)."""
    pipeline = build_pipeline(fake_vision_client, [])
    pipeline._type_handler.check_planogram_compliance = MagicMock(
        return_value=[
            _shelf_result("header", ComplianceStatus.COMPLIANT, 1.0),
            _shelf_result("top", ComplianceStatus.NON_COMPLIANT, 0.5),
        ]
    )
    result = await pipeline.run(synthetic_shelf_image)
    assert result["overall_compliance_score"] == pytest.approx(0.75)
    assert result["overall_compliant"] is False

    pipeline._type_handler.check_planogram_compliance = MagicMock(
        return_value=[
            _shelf_result("header", ComplianceStatus.COMPLIANT, 0.9),
            _shelf_result("top", ComplianceStatus.COMPLIANT, 0.81),
        ]
    )
    result = await pipeline.run(synthetic_shelf_image)
    assert result["overall_compliance_score"] == pytest.approx(0.855)
    assert result["overall_compliant"] is True


async def test_legacy_empty_results_is_compliant_today(fake_vision_client, synthetic_shelf_image) -> None:
    """TODAY's quirk (plan.py:347-351): an empty result list ⇒ score 0.0 but overall_compliant True.

    The type-hooks task (TASK-3442) intentionally flips ONLY this expectation to False — keep it isolated here.
    """
    pipeline = build_pipeline(fake_vision_client, [])
    pipeline._type_handler.check_planogram_compliance = MagicMock(return_value=[])
    result = await pipeline.run(synthetic_shelf_image)
    assert result["overall_compliance_score"] == 0.0
    assert result["overall_compliant"] is True


EIGHT_KEYS = {
    "step3_compliance_results",
    "compliance_results",
    "overall_compliance_score",
    "overall_compliant",
    "identified_products",
    "shelf_regions",
    "rendered_image",
    "overlay_path",
}


async def test_legacy_result_keys_and_output_files(fake_vision_client, synthetic_shelf_image, tmp_path: Path) -> None:
    """Eight keys, same list object twice, and the render/overlay naming with and without image_id."""
    pipeline = build_pipeline(fake_vision_client, [])
    plain = await pipeline.run(synthetic_shelf_image, output_dir=tmp_path)
    assert EIGHT_KEYS <= set(plain)  # additive keys are allowed later
    assert plain["compliance_results"] is plain["step3_compliance_results"]
    assert isinstance(plain["rendered_image"], Image.Image)
    assert plain["overlay_path"] == str(tmp_path / "compliance_render.png") and Path(plain["overlay_path"]).is_file()
    assert (tmp_path / "debug_step1_roi.png").is_file()

    await pipeline.run(synthetic_shelf_image, output_dir=tmp_path, image_id="store7")
    assert (tmp_path / "compliance_render_store7.png").is_file()
    assert (tmp_path / "debug_step1_roi_store7.png").is_file()

    before = sorted(p.name for p in tmp_path.iterdir())
    bare = await pipeline.run(synthetic_shelf_image)
    assert bare["overlay_path"] is None
    assert sorted(p.name for p in tmp_path.iterdir()) == before
