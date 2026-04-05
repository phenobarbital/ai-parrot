"""Unit tests for Detection Grid Models (TASK-583)."""
import pytest
from parrot_pipelines.planogram.grid.models import GridType, DetectionGridConfig, GridCell


class TestGridType:
    """Tests for GridType enum."""

    def test_enum_values(self):
        """All expected enum values exist."""
        assert GridType.NO_GRID == "no_grid"
        assert GridType.HORIZONTAL_BANDS == "horizontal_bands"
        assert GridType.MATRIX_GRID == "matrix_grid"
        assert GridType.ZONE_GRID == "zone_grid"
        assert GridType.FLAT_GRID == "flat_grid"

    def test_json_serializable(self):
        """GridType value is a plain string for JSON serialization."""
        assert GridType.NO_GRID.value == "no_grid"
        assert isinstance(GridType.HORIZONTAL_BANDS.value, str)


class TestDetectionGridConfig:
    """Tests for DetectionGridConfig model."""

    def test_defaults(self):
        """Default construction produces NoGrid with expected values."""
        config = DetectionGridConfig()
        assert config.grid_type == GridType.NO_GRID
        assert config.overlap_margin == 0.05
        assert config.max_image_size == 1024
        assert config.rows is None
        assert config.cols is None
        assert config.flat_divisions is None
        assert config.zones is None

    def test_custom_values(self):
        """Custom values accepted correctly."""
        config = DetectionGridConfig(
            grid_type=GridType.HORIZONTAL_BANDS,
            overlap_margin=0.10,
            max_image_size=512,
        )
        assert config.grid_type == GridType.HORIZONTAL_BANDS
        assert config.overlap_margin == 0.10
        assert config.max_image_size == 512

    def test_overlap_margin_max_bound(self):
        """overlap_margin rejects values above 0.20."""
        with pytest.raises(Exception):
            DetectionGridConfig(overlap_margin=0.5)

    def test_overlap_margin_min_bound(self):
        """overlap_margin rejects negative values."""
        with pytest.raises(Exception):
            DetectionGridConfig(overlap_margin=-0.01)

    def test_overlap_margin_boundary_valid(self):
        """overlap_margin at exactly 0.0 and 0.20 are accepted."""
        c1 = DetectionGridConfig(overlap_margin=0.0)
        assert c1.overlap_margin == 0.0
        c2 = DetectionGridConfig(overlap_margin=0.20)
        assert c2.overlap_margin == 0.20

    def test_matrix_grid_fields(self):
        """rows and cols accepted for MATRIX_GRID."""
        config = DetectionGridConfig(
            grid_type=GridType.MATRIX_GRID,
            rows=3,
            cols=4,
        )
        assert config.rows == 3
        assert config.cols == 4

    def test_zones_field(self):
        """zones accepted for ZONE_GRID."""
        zones = [{"name": "top", "y_start_ratio": 0.0, "y_end_ratio": 0.4}]
        config = DetectionGridConfig(grid_type=GridType.ZONE_GRID, zones=zones)
        assert config.zones == zones


class TestGridCell:
    """Tests for GridCell model."""

    def test_construction(self):
        """Full construction with all fields."""
        cell = GridCell(
            cell_id="shelf_top",
            bbox=(100, 50, 900, 250),
            expected_products=["ES-C220", "ES-580W"],
            reference_image_keys=["ES-C220", "ES-580W"],
            level="top",
        )
        assert cell.cell_id == "shelf_top"
        assert cell.bbox == (100, 50, 900, 250)
        assert cell.expected_products == ["ES-C220", "ES-580W"]
        assert cell.reference_image_keys == ["ES-C220", "ES-580W"]
        assert cell.level == "top"

    def test_defaults(self):
        """Minimal construction uses correct defaults."""
        cell = GridCell(cell_id="test", bbox=(0, 0, 100, 100))
        assert cell.expected_products == []
        assert cell.reference_image_keys == []
        assert cell.level is None

    def test_bbox_is_tuple_of_ints(self):
        """bbox must be a 4-tuple of integers."""
        cell = GridCell(cell_id="c", bbox=(10, 20, 200, 300))
        x1, y1, x2, y2 = cell.bbox
        assert all(isinstance(v, int) for v in (x1, y1, x2, y2))
