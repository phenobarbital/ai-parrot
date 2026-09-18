"""Characterization tests: fact-tag OCR, corroboration, shelf assignment, illumination — as they behave TODAY (FEAT-574)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, List, Optional
from unittest.mock import MagicMock

import pytest

from parrot.models.detections import DetectionBox, IdentifiedProduct, ShelfRegion
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.types import ProductOnShelves

RAW_CONFIG = {
    "brand": "TestBrand",
    "category": "Scanners",
    "aisle": {"name": "Electronics > Test", "lighting_conditions": "normal"},
    "shelves": [
        {
            "level": "header",
            "height_ratio": 0.2,
            "is_background": True,
            "products": [{"name": "TestBrand Backlit", "product_type": "promotional_graphic"}],
        },
        {
            "level": "top",
            "height_ratio": 0.4,
            "products": [{"name": "ES-400", "product_type": "product"}, {"name": "RR-60", "product_type": "product"}],
        },
        {"level": "bottom", "height_ratio": 0.4, "products": [{"name": "DS-770", "product_type": "product"}]},
    ],
}


def box(x1: int, y1: int, x2: int, y2: int) -> DetectionBox:
    """A detection box with confidence 0.9."""
    return DetectionBox(x1=x1, y1=y1, x2=x2, y2=y2, confidence=0.9)


def prod(
    model: Optional[str],
    ptype: str = "product",
    b: Optional[DetectionBox] = None,
    shelf_location: Optional[str] = None,
    **extra: Any,
) -> IdentifiedProduct:
    """An identified product."""
    return IdentifiedProduct(
        product_type=ptype, product_model=model, confidence=0.9, detection_box=b, shelf_location=shelf_location, **extra
    )


def regions() -> List[ShelfRegion]:
    """header (background) y∈[0,200), top y∈[200,500), bottom y∈[500,1000)."""
    return [
        ShelfRegion(shelf_id="h", level="header", bbox=box(0, 0, 800, 200), is_background=True),
        ShelfRegion(shelf_id="t", level="top", bbox=box(0, 200, 800, 500)),
        ShelfRegion(shelf_id="b", level="bottom", bbox=box(0, 500, 800, 1000)),
    ]


@pytest.fixture
def handler(fake_vision_client: Any) -> ProductOnShelves:
    """Real ProductOnShelves; the SAME fake is both roi_client and llm (refactor-proof)."""
    config = PlanogramConfig(
        config_name="c",
        planogram_type="product_on_shelves",
        planogram_config=RAW_CONFIG,
        roi_detection_prompt="roi",
        object_identification_prompt="objects",
    )
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.pos.helpers")
    pipeline.roi_client = fake_vision_client
    pipeline.llm = fake_vision_client
    pipeline._downscale_image = MagicMock(side_effect=lambda img, **kw: img)
    return ProductOnShelves(pipeline=pipeline, config=config)


# --------------------------------------------------------------------------- Part 2: illumination and fact-tag OCR


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("The panel is dull.\nLIGHT_OFF", "illumination_status: OFF"),
        ("Uniform glow.\nLIGHT_ON", "illumination_status: ON"),
        ("no verdict at all", "illumination_status: ON"),  # anything without LIGHT_OFF ⇒ ON (:247)
        ("", "illumination_status: ON"),
    ],
)
async def test_check_illumination_answer_parsing(
    handler, fake_vision_client, synthetic_shelf_image, answer: str, expected: str
) -> None:
    """LIGHT_OFF anywhere in the answer ⇒ OFF; everything else ⇒ ON."""
    fake_vision_client.queue("ask_to_image", answer)
    assert await handler._check_illumination(synthetic_shelf_image) == expected
    call = fake_vision_client.calls_to("ask_to_image")[0]
    assert call["kwargs"]["no_memory"] is True and call["kwargs"]["max_tokens"] == 128  # never assert "model"


async def test_check_illumination_failure_returns_none(handler, fake_vision_client, synthetic_shelf_image) -> None:
    """LLM failure ⇒ None (caller skips the penalty), never an exception."""
    fake_vision_client.queue("ask_to_image", RuntimeError("503"))
    assert await handler._check_illumination(synthetic_shelf_image) is None


async def test_check_illumination_crop_precedence(handler, fake_vision_client, synthetic_shelf_image) -> None:
    """zone_bbox (pixels) wins over roi.bbox (fractions) which wins over the full image."""
    zone = box(100, 0, 700, 200)
    roi = SimpleNamespace(bbox=SimpleNamespace(x1=0.0, y1=0.0, x2=0.5, y2=0.5))
    await handler._check_illumination(synthetic_shelf_image, zone_bbox=zone, roi=roi)
    await handler._check_illumination(synthetic_shelf_image, roi=roi)
    await handler._check_illumination(synthetic_shelf_image)
    sizes = [c["image_size"] for c in fake_vision_client.calls_to("ask_to_image")]
    assert sizes == [(600, 200), (400, 500), (800, 1000)]

    await handler._check_illumination(synthetic_shelf_image, planogram_description=SimpleNamespace(brand="TestBrand"))
    prompts = [c["prompt"] for c in fake_vision_client.calls_to("ask_to_image")]
    assert "a TestBrand backlit" in prompts[-1]
    assert "a backlit" in prompts[0]


async def test_ocr_fact_tags_strip_per_foreground_shelf(handler, fake_vision_client, synthetic_shelf_image) -> None:
    """No detected tags: one call per NON-background shelf, fixed strip at the shelf's bottom edge."""
    fake_vision_client.queue("ask_to_image", "ES-400, 'rr-60'", "UNKNOWN")
    products = [prod("ES-400", b=box(100, 250, 300, 480)), prod("DS-770", b=box(350, 600, 500, 950))]
    got = await handler._ocr_fact_tags(
        products, synthetic_shelf_image, handler.config.get_planogram_description(), shelf_regions=regions()
    )
    assert got == {"top": ["ES-400", "RR-60"]}  # upper-cased, quotes stripped, UNKNOWN shelf absent
    calls = fake_vision_client.calls_to("ask_to_image")
    assert len(calls) == 2  # header is background ⇒ skipped
    assert calls[0]["image_size"] == (460, 75)  # x: [100-30, 500+30]; y: [500-55, 500+20]
    assert calls[1]["image_size"] == (460, 55)  # y: [945, 1000] clamped to the image
    assert "ES-400, RR-60, DS-770" in calls[0]["prompt"]


async def test_ocr_fact_tags_detected_tags_refine_rows(handler, fake_vision_client, synthetic_shelf_image) -> None:
    """Detected fact tags set the y-span (±pad) and receive the raw OCR text."""
    tag = prod(None, "fact_tag", b=box(120, 470, 180, 490), shelf_location="top")
    fake_vision_client.queue("ask_to_image", "ES-400")
    got = await handler._ocr_fact_tags(
        [tag], synthetic_shelf_image, handler.config.get_planogram_description(), shelf_regions=[regions()[1]]
    )
    assert got == {"top": ["ES-400"]} and tag.ocr_text == "ES-400"
    assert fake_vision_client.calls_to("ask_to_image")[0]["image_size"] == (120, 30)


async def test_ocr_fact_tags_isolates_shelf_failure(handler, fake_vision_client, synthetic_shelf_image) -> None:
    """An exception on one shelf is logged; the other shelf is still read."""
    fake_vision_client.queue("ask_to_image", RuntimeError("boom"), "DS-770")
    got = await handler._ocr_fact_tags(
        [], synthetic_shelf_image, handler.config.get_planogram_description(), shelf_regions=regions()
    )
    assert got == {"bottom": ["DS-770"]}


# --------------------------------------------------------------------------- Part 3: corroboration and assignment


def test_corroborate_injects_missing_expected_model(handler) -> None:
    """OCR'd model expected on the shelf but not detected ⇒ synthetic product injected in place."""
    products = [prod("ES-400", shelf_location="top")]
    handler._corroborate_products_with_fact_tags(
        products, {"top": ["ES-400", "RR-60", "RR-60"]}, handler.config.get_planogram_description()
    )
    assert [p.product_model for p in products] == ["ES-400", "RR-60"]  # no duplicate within one run
    injected = products[-1]
    assert (injected.product_type, injected.shelf_location, injected.confidence) == ("product", "top", 0.85)
    assert injected.visual_features == ["fact_tag_confirmed:RR-60"] and injected.ocr_text == "fact_tag_ocr:RR-60"


@pytest.mark.parametrize(
    "ocr_model,reason",
    [
        ("REWARDS", "cannot be normalised"),
        ("ZZ-999", "not expected on this shelf"),
        ("DS-770", "belongs to another shelf"),
    ],
)
def test_corroborate_skip_rules(handler, ocr_model: str, reason: str) -> None:
    """Each skip rule prevents an injection."""
    products: List[IdentifiedProduct] = []
    handler._corroborate_products_with_fact_tags(
        products, {"top": [ocr_model]}, handler.config.get_planogram_description()
    )
    assert products == [], reason


def test_assign_products_default_max_overlap(handler) -> None:
    """Default mode: the shelf with the largest vertical overlap wins; structural types are untouched."""
    a = prod("ES-400", b=box(100, 250, 300, 480))  # fully inside 'top'
    straddle = prod("RR-60", b=box(320, 400, 480, 900))  # 100 px in top, 400 px in bottom
    gap = prod(None, "gap", b=box(0, 250, 50, 300), shelf_location="untouched")
    handler._assign_products_to_shelves([a, straddle, gap], regions())
    assert (a.shelf_location, straddle.shelf_location, gap.shelf_location) == ("top", "bottom", "untouched")


def test_assign_products_promotional_and_missing_box(handler) -> None:
    """Promos prefer the background shelf when their centre is inside it; box-less products get the middle shelf."""
    backlit = prod("TestBrand Backlit", "promotional_graphic", b=box(100, 20, 700, 180))
    low_graphic = prod("Comparison table", "promotional_graphic", b=box(100, 700, 700, 900))
    boxless = prod("ES-400")
    boxless_valid = prod("DS-770", shelf_location="bottom")
    handler._assign_products_to_shelves([backlit, low_graphic, boxless, boxless_valid], regions())
    assert backlit.shelf_location == "header"
    assert low_graphic.shelf_location == "bottom"  # centre below the background shelf ⇒ spatial
    assert boxless_valid.shelf_location == "bottom"  # valid LLM location kept
    assert boxless.shelf_location == "bottom"  # foreground = [top, bottom], len // 2 = 1


def test_assign_products_y1_mode_uses_centre_bottom_up(handler) -> None:
    """use_y1_assignment=True: bbox CENTRE decides (bottom→top), bbox y1 is only the secondary hint."""
    by_centre = prod("RR-60", b=box(320, 400, 480, 900))  # centre y=650 ⇒ bottom
    handler._assign_products_to_shelves([by_centre], regions(), use_y1_assignment=True)
    assert by_centre.shelf_location == "bottom"

    gapped = [
        ShelfRegion(shelf_id="t", level="top", bbox=box(0, 200, 800, 450)),
        ShelfRegion(shelf_id="b", level="bottom", bbox=box(0, 550, 800, 1000)),
    ]
    by_y1 = prod("ES-400", b=box(100, 440, 300, 560))  # centre 500 in the gap, y1 440 inside 'top'
    handler._assign_products_to_shelves([by_y1], gapped, use_y1_assignment=True)
    assert by_y1.shelf_location == "top"


def test_assign_products_no_shelves_is_noop(handler) -> None:
    """No shelves ⇒ nothing assigned, returns None."""
    p = prod("ES-400", b=box(1, 1, 5, 5), shelf_location="keep")
    assert handler._assign_products_to_shelves([p], []) is None
    assert p.shelf_location == "keep"
