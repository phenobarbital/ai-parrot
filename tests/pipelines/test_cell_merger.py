"""Unit tests for CellResultMerger (TASK-586)."""
import pytest
from parrot_pipelines.planogram.grid.merger import CellResultMerger, _compute_iou
from parrot_pipelines.planogram.grid.models import GridCell
from parrot.models.detections import DetectionBox, IdentifiedProduct


def _make_box(x1: int, y1: int, x2: int, y2: int, conf: float = 0.9) -> DetectionBox:
    """Create a DetectionBox with required fields."""
    return DetectionBox(
        x1=x1, y1=y1, x2=x2, y2=y2,
        confidence=conf,
        class_id=0,
        class_name="llm_detected",
        area=abs(x2 - x1) * abs(y2 - y1),
    )


def _make_product(
    model: str,
    confidence: float = 0.9,
    bbox: DetectionBox = None,
) -> IdentifiedProduct:
    """Create a minimal IdentifiedProduct."""
    return IdentifiedProduct(
        product_type="product",
        product_model=model,
        confidence=confidence,
        detection_box=bbox,
    )


class TestComputeIoU:
    """Tests for the _compute_iou helper."""

    def test_identical_boxes(self):
        """Identical boxes have IoU of 1.0."""
        box = _make_box(0, 0, 100, 100)
        assert _compute_iou(box, box) == pytest.approx(1.0)

    def test_no_overlap(self):
        """Non-overlapping boxes have IoU of 0.0."""
        a = _make_box(0, 0, 50, 50)
        b = _make_box(100, 100, 200, 200)
        assert _compute_iou(a, b) == 0.0

    def test_partial_overlap(self):
        """Partial overlap computes correct IoU."""
        a = _make_box(0, 0, 100, 100)
        b = _make_box(50, 50, 150, 150)
        # intersection = 50x50 = 2500, union = 10000+10000-2500 = 17500
        expected = 2500 / 17500
        assert _compute_iou(a, b) == pytest.approx(expected, abs=1e-6)

    def test_one_inside_other(self):
        """When one box is fully inside the other, IoU = area_small/area_large."""
        outer = _make_box(0, 0, 100, 100)
        inner = _make_box(25, 25, 75, 75)
        # intersection = 50*50 = 2500, union = 10000+2500-2500=10000
        assert _compute_iou(outer, inner) == pytest.approx(0.25)

    def test_symmetry(self):
        """IoU(a, b) == IoU(b, a)."""
        a = _make_box(0, 0, 80, 80)
        b = _make_box(40, 40, 120, 120)
        assert _compute_iou(a, b) == pytest.approx(_compute_iou(b, a))


class TestCellResultMerger:
    """Tests for CellResultMerger.merge()."""

    def test_offset_correction(self):
        """Cell-relative coords become absolute after merge."""
        cell = GridCell(
            cell_id="top",
            bbox=(100, 50, 800, 300),
            expected_products=["ES-C220"],
        )
        # Detection at (10, 20, 50, 80) relative to cell origin (100, 50)
        product = _make_product("ES-C220", 0.9, _make_box(10, 20, 50, 80))
        merger = CellResultMerger()
        merged = merger.merge([(cell, [product])])

        assert len(merged) == 1
        box = merged[0].detection_box
        assert box.x1 == 110  # 10 + 100
        assert box.y1 == 70   # 20 + 50
        assert box.x2 == 150  # 50 + 100
        assert box.y2 == 130  # 80 + 50

    def test_iou_deduplication_keeps_higher_confidence(self):
        """Overlapping detections from adjacent cells — higher confidence wins."""
        cell_a = GridCell(cell_id="top", bbox=(0, 0, 800, 400), expected_products=["ES-C220"])
        cell_b = GridCell(cell_id="mid", bbox=(0, 350, 800, 750), expected_products=["ES-C220"])

        # Both detections map to same absolute region after offset
        # cell_a product: already at absolute coords (no offset needed for x, but +0 for y)
        product_a = _make_product("ES-C220", 0.95, _make_box(100, 200, 300, 380))
        # cell_b product at (100, -150+...) relative... let's use:
        # cell_b bbox=(0,350,...), product at (100, -150, 300, 30) -> after offset (100,200,300,380)
        product_b = _make_product("ES-C220", 0.70, _make_box(100, -150, 300, 30))

        merger = CellResultMerger()
        merged = merger.merge([(cell_a, [product_a]), (cell_b, [product_b])])

        # After offsets: both at (100,200,300,380) — should deduplicate
        assert len(merged) == 1
        assert merged[0].confidence == pytest.approx(0.95)

    def test_no_dedup_below_threshold(self):
        """Non-overlapping detections from different cells are both kept."""
        cell_a = GridCell(cell_id="top", bbox=(0, 0, 800, 400))
        cell_b = GridCell(cell_id="mid", bbox=(0, 400, 800, 800))

        product_a = _make_product("ES-C220", 0.9, _make_box(10, 10, 100, 100))
        product_b = _make_product("V39-II", 0.8, _make_box(10, 10, 100, 100))

        merger = CellResultMerger()
        # After offsets: product_a at (10,10,100,100), product_b at (10,410,100,500)
        merged = merger.merge([(cell_a, [product_a]), (cell_b, [product_b])])

        assert len(merged) == 2

    def test_out_of_place_tagging_via_extra(self):
        """Product not in cell's expected_products gets out_of_place in extra."""
        cell = GridCell(
            cell_id="top",
            bbox=(0, 0, 800, 300),
            expected_products=["ES-C220"],
        )
        # V39-II is not expected in top shelf cell
        unexpected = _make_product("V39-II", 0.8, _make_box(10, 10, 100, 100))
        merger = CellResultMerger()
        merged = merger.merge([(cell, [unexpected])])

        assert len(merged) == 1
        p = merged[0]
        # Should have out_of_place flag (either attribute or in extra dict)
        has_flag = (
            getattr(p, "out_of_place", False) is True
            or p.extra.get("out_of_place") == "true"
        )
        assert has_flag

    def test_expected_product_not_tagged_out_of_place(self):
        """Product in expected_products is NOT tagged out_of_place."""
        cell = GridCell(
            cell_id="top",
            bbox=(0, 0, 800, 300),
            expected_products=["ES-C220"],
        )
        expected = _make_product("ES-C220", 0.9, _make_box(10, 10, 100, 100))
        merger = CellResultMerger()
        merged = merger.merge([(cell, [expected])])

        assert len(merged) == 1
        p = merged[0]
        has_flag = (
            getattr(p, "out_of_place", False) is True
            or p.extra.get("out_of_place") == "true"
        )
        assert not has_flag

    def test_none_detection_box_handled(self):
        """Products without detection_box pass through without error."""
        cell = GridCell(cell_id="top", bbox=(0, 0, 800, 300), expected_products=["ES-C220"])
        product = _make_product("ES-C220", 0.7, bbox=None)
        merger = CellResultMerger()
        merged = merger.merge([(cell, [product])])

        assert len(merged) == 1
        assert merged[0].detection_box is None

    def test_empty_cell_results(self):
        """Empty cell_results returns empty list without error."""
        merger = CellResultMerger()
        merged = merger.merge([])
        assert merged == []

    def test_multiple_cells_aggregated(self):
        """Products from multiple cells are all included (when no overlap)."""
        cell_a = GridCell(cell_id="top", bbox=(0, 0, 800, 300))
        cell_b = GridCell(cell_id="mid", bbox=(0, 300, 800, 600))
        cell_c = GridCell(cell_id="bot", bbox=(0, 600, 800, 900))

        merger = CellResultMerger()
        merged = merger.merge([
            (cell_a, [_make_product("A", bbox=None)]),
            (cell_b, [_make_product("B", bbox=None)]),
            (cell_c, [_make_product("C", bbox=None)]),
        ])

        assert len(merged) == 3
        models = {p.product_model for p in merged}
        assert models == {"A", "B", "C"}
