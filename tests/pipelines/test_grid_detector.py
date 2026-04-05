"""Unit tests for GridDetector (TASK-587)."""
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock
from PIL import Image

from parrot_pipelines.planogram.grid.detector import GridDetector
from parrot_pipelines.planogram.grid.models import GridCell, DetectionGridConfig, GridType


def _make_llm(return_value=None, side_effect=None):
    """Build a mock LLM with async detect_objects."""
    llm = MagicMock()
    if side_effect is not None:
        llm.detect_objects = AsyncMock(side_effect=side_effect)
    else:
        llm.detect_objects = AsyncMock(
            return_value=return_value or [
                {
                    "label": "ES-C220",
                    "box_2d": [50, 10, 200, 150],
                    "confidence": 0.9,
                    "type": "product",
                }
            ]
        )
    return llm


def _make_image(width: int = 800, height: int = 600) -> Image.Image:
    """Create a blank test image."""
    return Image.new("RGB", (width, height), color=(128, 128, 128))


def _make_config(**kwargs) -> DetectionGridConfig:
    """Create a DetectionGridConfig."""
    return DetectionGridConfig(
        grid_type=GridType.HORIZONTAL_BANDS,
        max_image_size=512,
        **kwargs,
    )


class TestGridDetector:
    """Tests for GridDetector.detect_cells()."""

    @pytest.mark.asyncio
    async def test_parallel_execution_calls_llm_n_times(self):
        """N cells produce N LLM calls."""
        llm = _make_llm()
        detector = GridDetector(llm=llm, reference_images={}, logger=MagicMock())
        cells = [
            GridCell(cell_id="top", bbox=(0, 0, 800, 300), expected_products=["ES-C220"]),
            GridCell(cell_id="mid", bbox=(0, 300, 800, 600), expected_products=["V39-II"]),
        ]
        config = _make_config()
        image = _make_image()

        await detector.detect_cells(cells, image, config)

        assert llm.detect_objects.call_count == 2

    @pytest.mark.asyncio
    async def test_cell_failure_isolation(self):
        """One cell failing does not block results from other cells."""
        # First call raises exception, second succeeds
        llm = _make_llm(
            side_effect=[
                Exception("API error"),
                [
                    {
                        "label": "V39-II",
                        "box_2d": [50, 10, 200, 150],
                        "confidence": 0.8,
                        "type": "product",
                    }
                ],
            ]
        )
        detector = GridDetector(llm=llm, reference_images={}, logger=MagicMock())
        cells = [
            GridCell(cell_id="top", bbox=(0, 0, 800, 300), expected_products=["ES-C220"]),
            GridCell(cell_id="mid", bbox=(0, 300, 800, 600), expected_products=["V39-II"]),
        ]
        config = _make_config()
        image = _make_image()

        results = await detector.detect_cells(cells, image, config)

        # Second cell's product should be in results
        assert any(p.product_model == "V39-II" for p in results)

    @pytest.mark.asyncio
    async def test_reference_filtering_by_keys(self):
        """Only reference images for the cell's expected products are passed."""
        llm = _make_llm(return_value=[])
        refs = {
            "ES-C220": "/ref/es_c220.jpg",
            "V39-II": "/ref/v39.jpg",
            "ES-580W": "/ref/es_580w.jpg",
        }
        detector = GridDetector(llm=llm, reference_images=refs, logger=MagicMock())
        cells = [
            GridCell(
                cell_id="top",
                bbox=(0, 0, 800, 300),
                expected_products=["ES-C220"],
                reference_image_keys=["ES-C220"],
            ),
        ]
        config = _make_config()
        image = _make_image()

        await detector.detect_cells(cells, image, config)

        call_kwargs = llm.detect_objects.call_args
        passed_refs = call_kwargs.kwargs.get("reference_images") or call_kwargs[1].get("reference_images")
        # Only ES-C220 ref should be passed
        assert passed_refs == ["/ref/es_c220.jpg"]

    @pytest.mark.asyncio
    async def test_multi_reference_per_product(self):
        """A list of references per product key are all included."""
        llm = _make_llm(return_value=[])
        refs = {
            "ES-C220": ["/ref/es_c220_a.jpg", "/ref/es_c220_b.jpg"],
        }
        detector = GridDetector(llm=llm, reference_images=refs, logger=MagicMock())
        cells = [
            GridCell(
                cell_id="top",
                bbox=(0, 0, 800, 300),
                expected_products=["ES-C220"],
                reference_image_keys=["ES-C220"],
            ),
        ]
        config = _make_config()
        image = _make_image()

        await detector.detect_cells(cells, image, config)

        call_kwargs = llm.detect_objects.call_args
        passed_refs = call_kwargs.kwargs.get("reference_images") or call_kwargs[1].get("reference_images")
        assert len(passed_refs) == 2
        assert "/ref/es_c220_a.jpg" in passed_refs
        assert "/ref/es_c220_b.jpg" in passed_refs

    @pytest.mark.asyncio
    async def test_returns_merged_products(self):
        """Products from multiple cells are merged and returned."""
        llm = _make_llm(
            side_effect=[
                [{"label": "ES-C220", "box_2d": [10, 5, 100, 80], "confidence": 0.9, "type": "product"}],
                [{"label": "V39-II", "box_2d": [10, 5, 100, 80], "confidence": 0.8, "type": "product"}],
            ]
        )
        detector = GridDetector(llm=llm, reference_images={}, logger=MagicMock())
        cells = [
            GridCell(cell_id="top", bbox=(0, 0, 800, 300), expected_products=["ES-C220"]),
            GridCell(cell_id="mid", bbox=(0, 300, 800, 600), expected_products=["V39-II"]),
        ]
        config = _make_config()
        image = _make_image()

        results = await detector.detect_cells(cells, image, config)

        models = {p.product_model for p in results}
        assert "ES-C220" in models
        assert "V39-II" in models

    @pytest.mark.asyncio
    async def test_all_cells_fail(self):
        """When all cells fail, returns empty list."""
        llm = _make_llm(side_effect=Exception("All fail"))
        detector = GridDetector(llm=llm, reference_images={}, logger=MagicMock())
        cells = [
            GridCell(cell_id="top", bbox=(0, 0, 800, 300)),
            GridCell(cell_id="mid", bbox=(0, 300, 800, 600)),
        ]
        config = _make_config()
        image = _make_image()

        results = await detector.detect_cells(cells, image, config)
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_cells_list(self):
        """Empty cells list returns empty list without LLM calls."""
        llm = _make_llm()
        detector = GridDetector(llm=llm, reference_images={}, logger=MagicMock())
        config = _make_config()
        image = _make_image()

        results = await detector.detect_cells([], image, config)
        assert results == []
        assert llm.detect_objects.call_count == 0

    def test_filter_references_empty_keys_returns_all(self):
        """Empty reference_image_keys falls back to all references."""
        refs = {"A": "/a.jpg", "B": "/b.jpg"}
        detector = GridDetector(
            llm=MagicMock(), reference_images=refs, logger=MagicMock()
        )
        result = detector._filter_references([])
        assert "/a.jpg" in result
        assert "/b.jpg" in result

    def test_filter_references_known_key(self):
        """Known key returns only that product's reference."""
        refs = {"A": "/a.jpg", "B": "/b.jpg"}
        detector = GridDetector(
            llm=MagicMock(), reference_images=refs, logger=MagicMock()
        )
        result = detector._filter_references(["A"])
        assert result == ["/a.jpg"]

    def test_filter_references_unknown_key_skipped(self):
        """Unknown keys are silently skipped."""
        refs = {"A": "/a.jpg"}
        detector = GridDetector(
            llm=MagicMock(), reference_images=refs, logger=MagicMock()
        )
        result = detector._filter_references(["UNKNOWN"])
        assert result == []
