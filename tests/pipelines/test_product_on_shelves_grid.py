"""Tests for ProductOnShelves grid-based detection refactor (TASK-590)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image

from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves
from parrot_pipelines.planogram.grid.models import DetectionGridConfig, GridType
from parrot_pipelines.planogram.grid.strategy import NoGrid
from parrot_pipelines.planogram.grid.horizontal_bands import HorizontalBands


def _make_image(w: int = 800, h: int = 600) -> Image.Image:
    return Image.new("RGB", (w, h), color=(200, 200, 200))


def _make_config(detection_grid=None) -> MagicMock:
    """Build a mock PlanogramConfig."""
    config = MagicMock()
    config.detection_grid = detection_grid
    config.object_identification_prompt = None
    config.get_planogram_description.return_value = MagicMock(shelves=[])
    return config


def _make_pipeline(reference_images=None) -> MagicMock:
    """Build a mock PlanogramCompliance pipeline."""
    pipeline = MagicMock()
    pipeline.logger = MagicMock()
    pipeline.reference_images = reference_images or {}
    pipeline.llm = MagicMock()
    pipeline.llm.detect_objects = AsyncMock(
        return_value=[
            {
                "label": "ES-C220",
                "box_2d": [50, 10, 200, 150],
                "confidence": 0.9,
                "type": "product",
            }
        ]
    )
    return pipeline


def _make_product_on_shelves(detection_grid=None, reference_images=None) -> ProductOnShelves:
    """Build a ProductOnShelves instance for testing."""
    config = _make_config(detection_grid=detection_grid)
    pipeline = _make_pipeline(reference_images=reference_images)
    return ProductOnShelves(pipeline=pipeline, config=config)


class TestGetGridStrategy:
    """Tests for ProductOnShelves.get_grid_strategy()."""

    def test_no_detection_grid_returns_no_grid(self):
        """No detection_grid config returns NoGrid."""
        pos = _make_product_on_shelves(detection_grid=None)
        strategy = pos.get_grid_strategy()
        assert isinstance(strategy, NoGrid)

    def test_no_grid_type_returns_no_grid(self):
        """detection_grid with NO_GRID type returns NoGrid."""
        pos = _make_product_on_shelves(
            detection_grid=DetectionGridConfig(grid_type=GridType.NO_GRID)
        )
        strategy = pos.get_grid_strategy()
        assert isinstance(strategy, NoGrid)

    def test_horizontal_bands_returns_horizontal_bands(self):
        """detection_grid with HORIZONTAL_BANDS returns HorizontalBands."""
        pos = _make_product_on_shelves(
            detection_grid=DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS)
        )
        strategy = pos.get_grid_strategy()
        assert isinstance(strategy, HorizontalBands)


class TestDetectObjects:
    """Tests for the detect_objects() grid/legacy path selection."""

    @pytest.mark.asyncio
    async def test_no_grid_uses_legacy_single_llm_call(self):
        """detection_grid=None triggers legacy path with 1 LLM call."""
        pos = _make_product_on_shelves(detection_grid=None)
        image = _make_image()

        products, shelves = await pos.detect_objects(img=image, roi=None, macro_objects=None)

        # Legacy path makes exactly 1 LLM call
        assert pos.pipeline.llm.detect_objects.call_count == 1

    @pytest.mark.asyncio
    async def test_no_grid_type_uses_legacy_path(self):
        """detection_grid with NO_GRID uses legacy path."""
        pos = _make_product_on_shelves(
            detection_grid=DetectionGridConfig(grid_type=GridType.NO_GRID)
        )
        image = _make_image()

        await pos.detect_objects(img=image, roi=None, macro_objects=None)

        # Legacy path: exactly 1 LLM call
        assert pos.pipeline.llm.detect_objects.call_count == 1

    @pytest.mark.asyncio
    async def test_horizontal_bands_uses_grid_path(self):
        """detection_grid with HORIZONTAL_BANDS triggers grid detection."""
        grid_config = DetectionGridConfig(
            grid_type=GridType.HORIZONTAL_BANDS,
            overlap_margin=0.0,
        )
        pos = _make_product_on_shelves(detection_grid=grid_config)

        # Set up planogram with 2 shelves
        planogram = MagicMock()
        shelf1 = MagicMock()
        shelf1.level = "top"
        shelf1.height_ratio = 0.5
        shelf1.products = []
        shelf2 = MagicMock()
        shelf2.level = "bottom"
        shelf2.height_ratio = 0.5
        shelf2.products = []
        planogram.shelves = [shelf1, shelf2]
        pos.config.get_planogram_description.return_value = planogram

        # LLM returns one detection per call
        pos.pipeline.llm.detect_objects = AsyncMock(return_value=[
            {"label": "ES-C220", "box_2d": [10, 5, 100, 80], "confidence": 0.9, "type": "product"}
        ])

        image = _make_image()
        products, shelves = await pos.detect_objects(img=image, roi=None, macro_objects=None)

        # Grid path: 1 call per shelf = 2 calls
        assert pos.pipeline.llm.detect_objects.call_count == 2

    @pytest.mark.asyncio
    async def test_roi_offset_applied_in_legacy_path(self):
        """Legacy path applies ROI offset to detection coords."""
        pos = _make_product_on_shelves(detection_grid=None)
        image = _make_image(800, 600)

        # Create a mock ROI at (100, 50, 700, 550)
        roi = MagicMock()
        roi.bbox = MagicMock()
        roi.bbox.get_pixel_coordinates.return_value = (100, 50, 700, 550)

        # LLM returns box at (10, 5, 100, 80) in crop-relative coords
        pos.pipeline.llm.detect_objects = AsyncMock(return_value=[
            {"label": "ES-C220", "box_2d": [10, 5, 100, 80], "confidence": 0.9, "type": "product"}
        ])

        products, _ = await pos.detect_objects(img=image, roi=roi, macro_objects=None)

        assert len(products) == 1
        box = products[0].detection_box
        # Legacy path: x1 = 10+100=110 (box_2d[0] is first coord, treated as x)
        # Actually box_2d = [ymin, xmin, ymax, xmax] = [10, 5, 100, 80]
        # In code: x1, y1, x2, y2 = box → 10+100=110, 5+50=55, 100+100=200, 80+50=130
        assert box.x1 == 10 + 100  # 110
        assert box.y1 == 5 + 50    # 55

    @pytest.mark.asyncio
    async def test_roi_offset_applied_in_grid_path(self):
        """Grid path applies ROI offset to merged detection coords."""
        grid_config = DetectionGridConfig(
            grid_type=GridType.HORIZONTAL_BANDS,
            overlap_margin=0.0,
        )
        pos = _make_product_on_shelves(detection_grid=grid_config)

        planogram = MagicMock()
        shelf = MagicMock()
        shelf.level = "top"
        shelf.height_ratio = 1.0
        shelf.products = []
        planogram.shelves = [shelf]
        pos.config.get_planogram_description.return_value = planogram

        # ROI at (100, 50, ...)
        roi = MagicMock()
        roi.bbox = MagicMock()
        roi.bbox.get_pixel_coordinates.return_value = (100, 50, 700, 550)

        # LLM returns box at (10, 5, 100, 80)
        pos.pipeline.llm.detect_objects = AsyncMock(return_value=[
            {"label": "ES-C220", "box_2d": [10, 5, 100, 80], "confidence": 0.9, "type": "product"}
        ])

        image = _make_image(800, 600)
        products, _ = await pos.detect_objects(img=image, roi=roi, macro_objects=None)

        assert len(products) >= 1
        box = products[0].detection_box
        # Grid cell is at (0,0,...) in crop space, then offset applied
        # box_2d [10, 5, 100, 80] → parsed in detector as x1=5, y1=10
        # then ROI offset: x1 += 100, y1 += 50
        assert box.x1 == 5 + 100   # 105
        assert box.y1 == 10 + 50   # 60

    @pytest.mark.asyncio
    async def test_returns_tuple_format(self):
        """detect_objects always returns (List[IdentifiedProduct], List[ShelfRegion])."""
        pos = _make_product_on_shelves(detection_grid=None)
        image = _make_image()
        result = await pos.detect_objects(img=image, roi=None, macro_objects=None)

        assert isinstance(result, tuple)
        assert len(result) == 2
        products, shelves = result
        assert isinstance(products, list)
        assert isinstance(shelves, list)
