"""Unit tests for HorizontalBands grid strategy (TASK-585)."""
import pytest
from unittest.mock import MagicMock

from parrot_pipelines.planogram.grid.horizontal_bands import HorizontalBands
from parrot_pipelines.planogram.grid.models import GridType, DetectionGridConfig
from parrot_pipelines.planogram.grid.strategy import get_strategy


def _make_shelf(level: str, height_ratio: float, product_names: list) -> MagicMock:
    """Create a mock ShelfConfig."""
    shelf = MagicMock()
    shelf.level = level
    shelf.height_ratio = height_ratio
    products = []
    for name in product_names:
        p = MagicMock()
        p.name = name
        products.append(p)
    shelf.products = products
    return shelf


def _make_planogram(shelves: list) -> MagicMock:
    """Create a mock PlanogramDescription."""
    planogram = MagicMock()
    planogram.shelves = shelves
    return planogram


class TestHorizontalBands:
    """Tests for HorizontalBands.compute_cells()."""

    def test_three_shelves_produces_three_cells(self):
        """3 shelves produce exactly 3 cells."""
        strategy = HorizontalBands()
        config = DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS, overlap_margin=0.0)
        planogram = _make_planogram([
            _make_shelf("top", 0.34, ["ES-C220", "ES-580W"]),
            _make_shelf("middle", 0.25, ["V39-II"]),
            _make_shelf("bottom", 0.41, ["ES-C320W"]),
        ])
        cells = strategy.compute_cells(
            roi_bbox=(100, 0, 900, 1000),
            image_size=(1920, 1080),
            planogram_description=planogram,
            grid_config=config,
        )
        assert len(cells) == 3

    def test_cell_levels_match_shelf_levels(self):
        """Each cell's level and cell_id matches the shelf level."""
        strategy = HorizontalBands()
        config = DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS, overlap_margin=0.0)
        planogram = _make_planogram([
            _make_shelf("top", 0.34, []),
            _make_shelf("middle", 0.25, []),
            _make_shelf("bottom", 0.41, []),
        ])
        cells = strategy.compute_cells(
            roi_bbox=(100, 0, 900, 1000),
            image_size=(1920, 1080),
            planogram_description=planogram,
            grid_config=config,
        )
        assert cells[0].level == "top"
        assert cells[1].level == "middle"
        assert cells[2].level == "bottom"
        assert cells[0].cell_id == "top"
        assert cells[1].cell_id == "middle"
        assert cells[2].cell_id == "bottom"

    def test_vertical_allocation_by_height_ratio(self):
        """Bands are proportional to height_ratios with no overlap."""
        strategy = HorizontalBands()
        config = DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS, overlap_margin=0.0)
        planogram = _make_planogram([
            _make_shelf("top", 0.34, []),
            _make_shelf("middle", 0.25, []),
            _make_shelf("bottom", 0.41, []),
        ])
        # ROI: y from 0 to 1000, height = 1000
        cells = strategy.compute_cells(
            roi_bbox=(0, 0, 800, 1000),
            image_size=(800, 1000),
            planogram_description=planogram,
            grid_config=config,
        )
        # top: 0 to 340 (34% of 1000)
        assert cells[0].bbox[1] == 0
        assert cells[0].bbox[3] == 340

        # middle: 340 to 590 (340 + 25% of 1000)
        assert cells[1].bbox[1] == 340
        assert cells[1].bbox[3] == 590

        # bottom: 590 to 1000
        assert cells[2].bbox[1] == 590

    def test_x_coordinates_match_roi(self):
        """All cells span the full ROI width."""
        strategy = HorizontalBands()
        config = DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS, overlap_margin=0.0)
        planogram = _make_planogram([
            _make_shelf("top", 0.50, []),
            _make_shelf("bottom", 0.50, []),
        ])
        cells = strategy.compute_cells(
            roi_bbox=(100, 50, 900, 750),
            image_size=(1024, 768),
            planogram_description=planogram,
            grid_config=config,
        )
        for cell in cells:
            assert cell.bbox[0] == 100  # x1
            assert cell.bbox[2] == 900  # x2

    def test_overlap_extends_bands(self):
        """5% overlap extends each band beyond its nominal extent."""
        strategy = HorizontalBands()
        config = DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS, overlap_margin=0.05)
        planogram = _make_planogram([
            _make_shelf("top", 0.50, []),
            _make_shelf("bottom", 0.50, []),
        ])
        # ROI height = 1000, overlap_px = 50
        cells = strategy.compute_cells(
            roi_bbox=(0, 0, 800, 1000),
            image_size=(800, 1000),
            planogram_description=planogram,
            grid_config=config,
        )
        # First band: nominal top=0, bottom=500
        # With overlap: top=max(0, 0-50)=0, bottom=min(1000, 500+50)=550
        assert cells[0].bbox[1] == 0   # clamped to ROI top
        assert cells[0].bbox[3] == 550  # extended down

        # Second band: nominal top=500, bottom=1000
        # With overlap: top=max(0, 500-50)=450, bottom=min(1000, 1000+50)=1000
        assert cells[1].bbox[1] == 450  # extended up
        assert cells[1].bbox[3] == 1000  # clamped to ROI bottom

    def test_overlap_clamped_to_roi_bounds(self):
        """Overlap cannot extend beyond ROI boundaries."""
        strategy = HorizontalBands()
        config = DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS, overlap_margin=0.20)
        planogram = _make_planogram([
            _make_shelf("top", 0.50, []),
            _make_shelf("bottom", 0.50, []),
        ])
        cells = strategy.compute_cells(
            roi_bbox=(0, 100, 800, 600),
            image_size=(800, 800),
            planogram_description=planogram,
            grid_config=config,
        )
        # All cells must be within ROI bounds
        roi_y1, roi_y2 = 100, 600
        for cell in cells:
            assert cell.bbox[1] >= roi_y1
            assert cell.bbox[3] <= roi_y2

    def test_expected_products_per_band(self):
        """Each band only has products from its shelf config."""
        strategy = HorizontalBands()
        config = DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS, overlap_margin=0.0)
        planogram = _make_planogram([
            _make_shelf("top", 0.40, ["ES-C220", "ES-580W"]),
            _make_shelf("bottom", 0.60, ["V39-II", "ES-C320W"]),
        ])
        cells = strategy.compute_cells(
            roi_bbox=(0, 0, 800, 1000),
            image_size=(800, 1000),
            planogram_description=planogram,
            grid_config=config,
        )
        assert cells[0].expected_products == ["ES-C220", "ES-580W"]
        assert cells[1].expected_products == ["V39-II", "ES-C320W"]

    def test_reference_image_keys_match_expected_products(self):
        """reference_image_keys equals expected_products for each cell."""
        strategy = HorizontalBands()
        config = DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS, overlap_margin=0.0)
        planogram = _make_planogram([
            _make_shelf("top", 0.5, ["A", "B"]),
            _make_shelf("bottom", 0.5, ["C"]),
        ])
        cells = strategy.compute_cells(
            roi_bbox=(0, 0, 800, 1000),
            image_size=(800, 1000),
            planogram_description=planogram,
            grid_config=config,
        )
        for cell in cells:
            assert cell.reference_image_keys == cell.expected_products

    def test_empty_shelves_fallback(self):
        """No shelves returns a single full-ROI cell."""
        strategy = HorizontalBands()
        config = DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS)
        planogram = _make_planogram([])
        cells = strategy.compute_cells(
            roi_bbox=(0, 0, 800, 600),
            image_size=(800, 600),
            planogram_description=planogram,
            grid_config=config,
        )
        assert len(cells) == 1
        assert cells[0].cell_id == "full_roi"
        assert cells[0].bbox == (0, 0, 800, 600)

    def test_none_planogram_fallback(self):
        """None planogram_description returns a single full-ROI cell."""
        strategy = HorizontalBands()
        config = DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS)
        cells = strategy.compute_cells(
            roi_bbox=(0, 0, 800, 600),
            image_size=(800, 600),
            planogram_description=None,
            grid_config=config,
        )
        assert len(cells) == 1


class TestHorizontalBandsRegistry:
    """Tests confirming HorizontalBands is registered after module import."""

    def test_horizontal_bands_now_registered(self):
        """After importing horizontal_bands module, HORIZONTAL_BANDS is registered."""
        strategy = get_strategy(GridType.HORIZONTAL_BANDS)
        assert isinstance(strategy, HorizontalBands)
