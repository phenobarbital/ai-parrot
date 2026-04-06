"""Integration tests for grid detection with mocked LLM (TASK-591).

Tests the full grid detection flow from ProductOnShelves through
GridDetector back to merged IdentifiedProduct results.
Note: PlanogramCompliance is not imported directly to avoid the
transformers-version import chain. We test through ProductOnShelves
with a mocked pipeline, which is equivalent for detection tests.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from PIL import Image

from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.grid.models import DetectionGridConfig, GridType
from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves
from parrot.models.detections import IdentifiedProduct


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_image(w: int = 800, h: int = 600) -> Image.Image:
    """Create a blank test image."""
    return Image.new("RGB", (w, h), color=(128, 128, 128))


def _make_3_shelf_planogram_config() -> dict:
    """Return a planogram_config dict with 3 shelves and known products."""
    return {
        "brand": "Epson",
        "category": "printers",
        "aisle": {"name": "electronics", "category_hints": ["printers"]},
        "shelves": [
            {
                "level": "top",
                "height_ratio": 0.34,
                "products": [
                    {"name": "ES-C220", "product_type": "printer", "quantity_range": [1, 3]},
                    {"name": "ES-580W", "product_type": "printer", "quantity_range": [1, 2]},
                ],
            },
            {
                "level": "middle",
                "height_ratio": 0.25,
                "products": [
                    {"name": "V39-II", "product_type": "printer", "quantity_range": [1, 2]},
                ],
            },
            {
                "level": "bottom",
                "height_ratio": 0.41,
                "products": [
                    {"name": "ES-C320W", "product_type": "printer", "quantity_range": [1, 3]},
                ],
            },
        ],
    }


def _make_mock_llm(responses_by_call=None):
    """Build a mock LLM with per-call responses."""
    llm = MagicMock()
    if responses_by_call:
        llm.detect_objects = AsyncMock(side_effect=responses_by_call)
    else:
        llm.detect_objects = AsyncMock(return_value=[
            {"label": "ES-C220", "box_2d": [20, 10, 150, 120], "confidence": 0.9, "type": "product"}
        ])
    return llm


def _make_mock_pipeline(llm, reference_images=None):
    """Build a mock PlanogramCompliance pipeline."""
    pipeline = MagicMock()
    pipeline.logger = MagicMock()
    pipeline.llm = llm
    pipeline.reference_images = reference_images or {}
    return pipeline


def _make_pos(
    planogram_config: PlanogramConfig,
    llm=None,
    reference_images=None,
) -> ProductOnShelves:
    """Create a ProductOnShelves handler with mocked pipeline."""
    mock_llm = llm or _make_mock_llm()
    pipeline = _make_mock_pipeline(
        llm=mock_llm,
        reference_images=reference_images or planogram_config.reference_images,
    )
    pos = ProductOnShelves(pipeline=pipeline, config=planogram_config)
    return pos


@pytest.fixture
def planogram_config_with_grid():
    """PlanogramConfig with HorizontalBands grid enabled."""
    return PlanogramConfig(
        planogram_config=_make_3_shelf_planogram_config(),
        roi_detection_prompt="Find the product shelf endcap.",
        object_identification_prompt="Identify all products visible.",
        reference_images={
            "ES-C220": "/fake/es_c220.jpg",
            "ES-580W": "/fake/es_580w.jpg",
            "V39-II": "/fake/v39.jpg",
        },
        detection_grid=DetectionGridConfig(
            grid_type=GridType.HORIZONTAL_BANDS,
            overlap_margin=0.05,
        ),
    )


@pytest.fixture
def planogram_config_no_grid():
    """Same config but without detection_grid (legacy path)."""
    return PlanogramConfig(
        planogram_config=_make_3_shelf_planogram_config(),
        roi_detection_prompt="Find the product shelf endcap.",
        object_identification_prompt="Identify all products visible.",
        reference_images={
            "ES-C220": "/fake/es_c220.jpg",
        },
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGridIntegration:
    """Integration tests for the full grid detection path."""

    @pytest.mark.asyncio
    async def test_grid_mode_calls_llm_per_shelf(self, planogram_config_with_grid):
        """Grid mode with 3 shelves calls LLM 3 times (once per shelf cell)."""
        per_cell_response = [
            {"label": "ES-C220", "box_2d": [20, 10, 150, 120], "confidence": 0.9, "type": "product"},
        ]
        mock_llm = _make_mock_llm(responses_by_call=[per_cell_response] * 3)
        pos = _make_pos(planogram_config_with_grid, llm=mock_llm)
        image = _make_image()

        products, shelves = await pos.detect_objects(img=image, roi=None, macro_objects=None)

        # 3 cells → 3 LLM calls
        assert mock_llm.detect_objects.call_count == 3

    @pytest.mark.asyncio
    async def test_grid_mode_per_cell_hints_are_filtered(self, planogram_config_with_grid):
        """Each cell's LLM call only contains hints for that shelf's products."""
        mock_llm = _make_mock_llm(responses_by_call=[[], [], []])
        pos = _make_pos(planogram_config_with_grid, llm=mock_llm)
        image = _make_image()

        await pos.detect_objects(img=image, roi=None, macro_objects=None)

        # Verify per-cell prompts contain shelf-specific hints
        calls = mock_llm.detect_objects.call_args_list
        assert len(calls) == 3

        # First cell (top shelf) prompt should mention ES-C220, ES-580W
        top_prompt = calls[0].kwargs.get("prompt", "")
        assert "ES-C220" in top_prompt or "ES-580W" in top_prompt

        # Middle cell prompt should mention V39-II but NOT ES-C220
        mid_prompt = calls[1].kwargs.get("prompt", "")
        assert "V39-II" in mid_prompt
        assert "ES-C220" not in mid_prompt

    @pytest.mark.asyncio
    async def test_grid_mode_products_merged(self, planogram_config_with_grid):
        """Products from all cells are merged into a single list."""
        mock_llm = _make_mock_llm(responses_by_call=[
            [{"label": "ES-C220", "box_2d": [20, 10, 150, 120], "confidence": 0.9, "type": "product"}],
            [{"label": "V39-II", "box_2d": [20, 10, 100, 80], "confidence": 0.85, "type": "product"}],
            [{"label": "ES-C320W", "box_2d": [20, 10, 100, 80], "confidence": 0.8, "type": "product"}],
        ])
        pos = _make_pos(planogram_config_with_grid, llm=mock_llm)
        image = _make_image()

        products, _ = await pos.detect_objects(img=image, roi=None, macro_objects=None)

        model_names = {p.product_model for p in products}
        assert "ES-C220" in model_names
        assert "V39-II" in model_names
        assert "ES-C320W" in model_names

    @pytest.mark.asyncio
    async def test_out_of_place_detection(self, planogram_config_with_grid):
        """Product detected in wrong cell gets out_of_place=True."""
        # Top shelf only expects ES-C220, ES-580W
        # If LLM returns V39-II for top shelf → out_of_place
        mock_llm = _make_mock_llm(responses_by_call=[
            [{"label": "V39-II", "box_2d": [20, 10, 150, 120], "confidence": 0.8, "type": "product"}],
            [],
            [],
        ])
        pos = _make_pos(planogram_config_with_grid, llm=mock_llm)
        image = _make_image()

        products, _ = await pos.detect_objects(img=image, roi=None, macro_objects=None)

        assert len(products) == 1
        p = products[0]
        assert p.product_model == "V39-II"
        # Should be tagged as out_of_place
        has_flag = (
            getattr(p, "out_of_place", False) is True
            or p.extra.get("out_of_place") == "true"
        )
        assert has_flag

    @pytest.mark.asyncio
    async def test_multi_reference_images_per_product(self, planogram_config_with_grid):
        """Multi-reference images per product are flattened and passed to LLM."""
        # Modify config to use list of refs for ES-C220
        planogram_config_with_grid.reference_images = {
            "ES-C220": ["/fake/es_c220_a.jpg", "/fake/es_c220_b.jpg"],
            "ES-580W": "/fake/es_580w.jpg",
        }
        mock_llm = _make_mock_llm(responses_by_call=[[], [], []])
        pos = _make_pos(
            planogram_config_with_grid,
            llm=mock_llm,
            reference_images=planogram_config_with_grid.reference_images,
        )
        image = _make_image()

        await pos.detect_objects(img=image, roi=None, macro_objects=None)

        # First cell (top shelf) expects ES-C220 and ES-580W
        top_call = mock_llm.detect_objects.call_args_list[0]
        passed_refs = top_call.kwargs.get("reference_images") or []
        # ES-C220 has 2 refs + ES-580W has 1 = 3 refs
        assert len(passed_refs) == 3

    @pytest.mark.asyncio
    async def test_cell_failure_does_not_fail_pipeline(self, planogram_config_with_grid):
        """One cell LLM failure doesn't fail the whole detection."""
        mock_llm = _make_mock_llm(responses_by_call=[
            Exception("API error"),  # top shelf fails
            [{"label": "V39-II", "box_2d": [20, 10, 100, 80], "confidence": 0.85, "type": "product"}],
            [],
        ])
        pos = _make_pos(planogram_config_with_grid, llm=mock_llm)
        image = _make_image()

        # Should not raise
        products, _ = await pos.detect_objects(img=image, roi=None, macro_objects=None)

        # Should contain V39-II from middle shelf
        assert any(p.product_model == "V39-II" for p in products)


class TestGridRegression:
    """Regression tests: grid-disabled path must behave identically to baseline."""

    @pytest.mark.asyncio
    async def test_no_grid_uses_single_llm_call(self, planogram_config_no_grid):
        """Without detection_grid, exactly 1 LLM call is made."""
        mock_llm = _make_mock_llm()
        pos = _make_pos(planogram_config_no_grid, llm=mock_llm)
        image = _make_image()

        await pos.detect_objects(img=image, roi=None, macro_objects=None)

        assert mock_llm.detect_objects.call_count == 1

    @pytest.mark.asyncio
    async def test_no_grid_returns_all_products_from_single_call(
        self, planogram_config_no_grid
    ):
        """Legacy path returns all products from the single LLM response."""
        mock_llm = _make_mock_llm(responses_by_call=[[
            {"label": "ES-C220", "box_2d": [20, 10, 150, 120], "confidence": 0.9, "type": "product"},
            {"label": "V39-II", "box_2d": [30, 20, 200, 150], "confidence": 0.8, "type": "product"},
        ]])
        pos = _make_pos(planogram_config_no_grid, llm=mock_llm)
        image = _make_image()

        products, _ = await pos.detect_objects(img=image, roi=None, macro_objects=None)

        assert len(products) == 2
        models = {p.product_model for p in products}
        assert "ES-C220" in models
        assert "V39-II" in models

    @pytest.mark.asyncio
    async def test_no_grid_products_have_no_out_of_place_flag(
        self, planogram_config_no_grid
    ):
        """Legacy path does not set out_of_place — default is False."""
        mock_llm = _make_mock_llm()
        pos = _make_pos(planogram_config_no_grid, llm=mock_llm)
        image = _make_image()

        products, _ = await pos.detect_objects(img=image, roi=None, macro_objects=None)

        for p in products:
            assert getattr(p, "out_of_place", False) is False
            assert p.extra.get("out_of_place") is None

    @pytest.mark.asyncio
    async def test_switching_between_modes_does_not_persist_state(
        self, planogram_config_with_grid, planogram_config_no_grid
    ):
        """Creating two ProductOnShelves instances with different modes is independent."""
        mock_llm_a = _make_mock_llm(responses_by_call=[[], [], []])
        mock_llm_b = _make_mock_llm()

        pos_a = _make_pos(planogram_config_with_grid, llm=mock_llm_a)
        pos_b = _make_pos(planogram_config_no_grid, llm=mock_llm_b)

        image = _make_image()
        await pos_a.detect_objects(img=image, roi=None, macro_objects=None)
        await pos_b.detect_objects(img=image, roi=None, macro_objects=None)

        # Grid pipeline: 3 calls; legacy pipeline: 1 call
        assert mock_llm_a.detect_objects.call_count == 3
        assert mock_llm_b.detect_objects.call_count == 1

    def test_all_grid_modules_importable(self):
        """All grid modules are importable without errors."""
        from parrot_pipelines.planogram.grid import (
            GridType,
            DetectionGridConfig,
            GridCell,
            AbstractGridStrategy,
            NoGrid,
            HorizontalBands,
            CellResultMerger,
            GridDetector,
            get_strategy,
        )
        assert all([
            GridType, DetectionGridConfig, GridCell,
            AbstractGridStrategy, NoGrid, HorizontalBands,
            CellResultMerger, GridDetector, get_strategy,
        ])
