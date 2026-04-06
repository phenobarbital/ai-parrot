"""Regression tests: validate no-grid path is unchanged (TASK-591).

These tests specifically target backward compatibility — the legacy
single-image detection path must behave identically to pre-refactor.
Note: PlanogramCompliance is not imported directly to avoid the
transformers-version import chain. We test through ProductOnShelves
with a mocked pipeline.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from PIL import Image

from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves
from parrot.models.detections import IdentifiedProduct, DetectionBox


def _make_image(w: int = 800, h: int = 600) -> Image.Image:
    return Image.new("RGB", (w, h))


def _make_pos(config: PlanogramConfig, llm) -> ProductOnShelves:
    """Build ProductOnShelves with a mocked pipeline."""
    pipeline = MagicMock()
    pipeline.logger = MagicMock()
    pipeline.llm = llm
    pipeline.reference_images = config.reference_images or {}
    return ProductOnShelves(pipeline=pipeline, config=config)


def _legacy_config(**overrides) -> PlanogramConfig:
    """Build a minimal PlanogramConfig without detection_grid."""
    base = dict(
        planogram_config={
            "brand": "Epson",
            "category": "printers",
            "aisle": {"name": "electronics", "category_hints": []},
            "shelves": [
                {
                    "level": "top",
                    "height_ratio": 0.5,
                    "products": [
                        {"name": "ES-C220", "product_type": "printer", "quantity_range": [1, 2]},
                    ],
                }
            ],
        },
        roi_detection_prompt="Find the endcap.",
        object_identification_prompt="Identify all products.",
        reference_images={"ES-C220": "/fake/ref.jpg"},
    )
    base.update(overrides)
    return PlanogramConfig(**base)


class TestLegacyPathRegression:
    """Regression suite: detection_grid=None must behave as before."""

    @pytest.mark.asyncio
    async def test_single_llm_call_made(self):
        """Exactly 1 LLM call — no parallelism."""
        llm = MagicMock()
        llm.detect_objects = AsyncMock(return_value=[
            {"label": "ES-C220", "box_2d": [10, 5, 100, 80], "confidence": 0.9, "type": "product"}
        ])
        config = _legacy_config()
        pos = _make_pos(config, llm)
        image = _make_image()
        await pos.detect_objects(img=image, roi=None, macro_objects=None)

        assert llm.detect_objects.call_count == 1

    @pytest.mark.asyncio
    async def test_all_reference_images_sent(self):
        """Legacy path sends all reference images (not filtered)."""
        llm = MagicMock()
        llm.detect_objects = AsyncMock(return_value=[])

        config = _legacy_config(reference_images={
            "A": "/a.jpg",
            "B": "/b.jpg",
            "C": "/c.jpg",
        })
        pos = _make_pos(config, llm)
        image = _make_image()
        await pos.detect_objects(img=image, roi=None, macro_objects=None)

        call_kwargs = llm.detect_objects.call_args.kwargs
        passed_refs = call_kwargs.get("reference_images", [])
        assert len(passed_refs) == 3

    @pytest.mark.asyncio
    async def test_offset_correction_applied(self):
        """ROI crop offset is applied to detection coordinates."""
        llm = MagicMock()
        llm.detect_objects = AsyncMock(return_value=[
            {"label": "ES-C220", "box_2d": [10, 5, 100, 80], "confidence": 0.9, "type": "product"}
        ])

        config = _legacy_config()
        pos = _make_pos(config, llm)
        image = _make_image()

        # ROI at x1=200, y1=100
        roi = MagicMock()
        roi.bbox = MagicMock()
        roi.bbox.get_pixel_coordinates.return_value = (200, 100, 700, 500)

        products, _ = await pos.detect_objects(img=image, roi=roi, macro_objects=None)

        assert len(products) == 1
        box = products[0].detection_box
        # box_2d [10, 5, 100, 80] + offset(200, 100) → x1=10+200=210, y1=5+100=105
        assert box.x1 == 210
        assert box.y1 == 105

    @pytest.mark.asyncio
    async def test_shelf_items_go_to_shelf_regions(self):
        """Items with 'shelf' in label go to shelf_regions, not products."""
        llm = MagicMock()
        llm.detect_objects = AsyncMock(return_value=[
            {"label": "shelf_top", "box_2d": [0, 0, 800, 200], "confidence": 0.95, "type": "shelf"},
            {"label": "ES-C220", "box_2d": [10, 5, 100, 80], "confidence": 0.9, "type": "product"},
        ])

        config = _legacy_config()
        pos = _make_pos(config, llm)
        image = _make_image()
        products, shelves = await pos.detect_objects(img=image, roi=None, macro_objects=None)

        assert len(products) == 1
        assert len(shelves) == 1
        assert shelves[0].level == "shelf_top"

    @pytest.mark.asyncio
    async def test_product_box_type_assigned(self):
        """Labels with 'box' in them get product_type='product_box'."""
        llm = MagicMock()
        llm.detect_objects = AsyncMock(return_value=[
            {"label": "ES-C220 box", "box_2d": [10, 5, 100, 80], "confidence": 0.8, "type": "product"},
        ])

        config = _legacy_config()
        pos = _make_pos(config, llm)
        image = _make_image()
        products, _ = await pos.detect_objects(img=image, roi=None, macro_objects=None)

        assert len(products) == 1
        assert products[0].product_type == "product_box"

    @pytest.mark.asyncio
    async def test_out_of_place_field_default_false(self):
        """Legacy path never sets out_of_place=True (default False)."""
        llm = MagicMock()
        llm.detect_objects = AsyncMock(return_value=[
            {"label": "UNKNOWN_PRODUCT", "box_2d": [10, 5, 100, 80], "confidence": 0.7, "type": "product"},
        ])

        config = _legacy_config()
        pos = _make_pos(config, llm)
        image = _make_image()
        products, _ = await pos.detect_objects(img=image, roi=None, macro_objects=None)

        for p in products:
            assert p.out_of_place is False

    @pytest.mark.asyncio
    async def test_empty_llm_response(self):
        """Empty LLM response returns empty product and shelf lists."""
        llm = MagicMock()
        llm.detect_objects = AsyncMock(return_value=[])

        config = _legacy_config()
        pos = _make_pos(config, llm)
        image = _make_image()
        products, shelves = await pos.detect_objects(img=image, roi=None, macro_objects=None)

        assert products == []
        assert shelves == []
