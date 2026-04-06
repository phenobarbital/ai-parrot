"""Unit tests for AbstractGridStrategy and NoGrid (TASK-584)."""
import pytest
from unittest.mock import MagicMock

from parrot_pipelines.planogram.grid.strategy import AbstractGridStrategy, NoGrid, get_strategy
from parrot_pipelines.planogram.grid.models import GridType, DetectionGridConfig, GridCell


def _make_planogram(shelf_products: list) -> MagicMock:
    """Build a minimal mock PlanogramDescription for testing.

    Args:
        shelf_products: List of lists of product name strings, one per shelf.

    Returns:
        A MagicMock mimicking PlanogramDescription with .shelves[].products[].name.
    """
    shelves = []
    for i, product_names in enumerate(shelf_products):
        products = []
        for name in product_names:
            p = MagicMock()
            p.name = name
            products.append(p)
        shelf = MagicMock()
        shelf.products = products
        shelf.level = ["top", "middle", "bottom"][i % 3]
        shelves.append(shelf)
    planogram = MagicMock()
    planogram.shelves = shelves
    return planogram


class TestNoGrid:
    """Tests for the NoGrid strategy."""

    def test_returns_single_cell(self):
        """NoGrid always returns exactly one cell."""
        strategy = NoGrid()
        config = DetectionGridConfig()
        cells = strategy.compute_cells(
            roi_bbox=(100, 50, 900, 750),
            image_size=(1920, 1080),
            planogram_description=_make_planogram([["ES-C220"], ["V39-II"]]),
            grid_config=config,
        )
        assert len(cells) == 1

    def test_cell_id_is_full_roi(self):
        """The single cell has cell_id='full_roi'."""
        strategy = NoGrid()
        config = DetectionGridConfig()
        cells = strategy.compute_cells(
            roi_bbox=(100, 50, 900, 750),
            image_size=(1920, 1080),
            planogram_description=_make_planogram([]),
            grid_config=config,
        )
        assert cells[0].cell_id == "full_roi"

    def test_cell_bbox_equals_roi_bbox(self):
        """The single cell's bbox matches the roi_bbox exactly."""
        strategy = NoGrid()
        config = DetectionGridConfig()
        roi = (100, 50, 900, 750)
        cells = strategy.compute_cells(
            roi_bbox=roi,
            image_size=(1920, 1080),
            planogram_description=_make_planogram([]),
            grid_config=config,
        )
        assert cells[0].bbox == roi

    def test_collects_all_products_from_all_shelves(self):
        """expected_products includes all product names from all shelves."""
        strategy = NoGrid()
        config = DetectionGridConfig()
        planogram = _make_planogram([
            ["ES-C220", "ES-580W"],
            ["V39-II"],
            ["ES-C320W"],
        ])
        cells = strategy.compute_cells(
            roi_bbox=(0, 0, 800, 600),
            image_size=(800, 600),
            planogram_description=planogram,
            grid_config=config,
        )
        products = cells[0].expected_products
        assert "ES-C220" in products
        assert "ES-580W" in products
        assert "V39-II" in products
        assert "ES-C320W" in products

    def test_reference_image_keys_match_products(self):
        """reference_image_keys equals expected_products."""
        strategy = NoGrid()
        config = DetectionGridConfig()
        cells = strategy.compute_cells(
            roi_bbox=(0, 0, 800, 600),
            image_size=(800, 600),
            planogram_description=_make_planogram([["A", "B"]]),
            grid_config=config,
        )
        assert cells[0].reference_image_keys == cells[0].expected_products

    def test_none_planogram_description(self):
        """NoGrid handles None planogram_description without error."""
        strategy = NoGrid()
        config = DetectionGridConfig()
        cells = strategy.compute_cells(
            roi_bbox=(0, 0, 500, 400),
            image_size=(500, 400),
            planogram_description=None,
            grid_config=config,
        )
        assert len(cells) == 1
        assert cells[0].expected_products == []

    def test_empty_shelves(self):
        """NoGrid with empty shelves returns cell with no expected products."""
        strategy = NoGrid()
        config = DetectionGridConfig()
        cells = strategy.compute_cells(
            roi_bbox=(0, 0, 800, 600),
            image_size=(800, 600),
            planogram_description=_make_planogram([]),
            grid_config=config,
        )
        assert cells[0].expected_products == []


class TestStrategyRegistry:
    """Tests for the get_strategy registry function."""

    def test_no_grid_registered(self):
        """get_strategy returns a NoGrid for GridType.NO_GRID."""
        strategy = get_strategy(GridType.NO_GRID)
        assert isinstance(strategy, NoGrid)

    def test_returns_fresh_instance_each_call(self):
        """Each call returns a new instance (strategies are stateless)."""
        s1 = get_strategy(GridType.NO_GRID)
        s2 = get_strategy(GridType.NO_GRID)
        assert s1 is not s2

    def test_unknown_type_raises_value_error(self):
        """Unregistered grid types raise ValueError."""
        with pytest.raises(ValueError):
            get_strategy(GridType.MATRIX_GRID)  # Not registered (future strategy)

    def test_abstract_strategy_is_abstract(self):
        """AbstractGridStrategy cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AbstractGridStrategy()  # type: ignore[abstract]
