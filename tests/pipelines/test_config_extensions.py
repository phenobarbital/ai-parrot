"""Tests for PlanogramConfig and IdentifiedProduct extensions (TASK-588)."""
import pytest
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.grid.models import DetectionGridConfig, GridType
from parrot.models.detections import IdentifiedProduct


# Minimal valid PlanogramConfig kwargs
_BASE_CONFIG = dict(
    planogram_config={"brand": "TestBrand", "shelves": []},
    roi_detection_prompt="Find the endcap.",
    object_identification_prompt="Identify products.",
)


class TestPlanogramConfigExtension:
    """Tests for the detection_grid and reference_images extensions."""

    def test_backward_compat_no_grid(self):
        """Existing config without detection_grid still works, defaults to None."""
        config = PlanogramConfig(**_BASE_CONFIG)
        assert config.detection_grid is None

    def test_with_detection_grid_horizontal_bands(self):
        """detection_grid with HORIZONTAL_BANDS is accepted."""
        config = PlanogramConfig(
            **_BASE_CONFIG,
            detection_grid=DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS),
        )
        assert config.detection_grid is not None
        assert config.detection_grid.grid_type == GridType.HORIZONTAL_BANDS

    def test_with_detection_grid_no_grid(self):
        """detection_grid with NO_GRID is accepted and equals default NoGrid."""
        config = PlanogramConfig(
            **_BASE_CONFIG,
            detection_grid=DetectionGridConfig(grid_type=GridType.NO_GRID),
        )
        assert config.detection_grid.grid_type == GridType.NO_GRID

    def test_detection_grid_field_is_optional(self):
        """detection_grid is Optional — omitting it is equivalent to None."""
        config = PlanogramConfig(**_BASE_CONFIG)
        assert config.detection_grid is None

    def test_reference_images_single_string(self):
        """Dict[str, str] reference_images still works (backward compat)."""
        config = PlanogramConfig(
            **_BASE_CONFIG,
            reference_images={"ES-C220": "/path/to/image.jpg"},
        )
        assert config.reference_images["ES-C220"] == "/path/to/image.jpg"

    def test_reference_images_list_of_strings(self):
        """Dict[str, List[str]] accepted for multi-reference per product."""
        config = PlanogramConfig(
            **_BASE_CONFIG,
            reference_images={"ES-C220": ["/path/1.jpg", "/path/2.jpg"]},
        )
        assert isinstance(config.reference_images["ES-C220"], list)
        assert len(config.reference_images["ES-C220"]) == 2

    def test_reference_images_empty_default(self):
        """No reference_images defaults to empty dict."""
        config = PlanogramConfig(**_BASE_CONFIG)
        assert config.reference_images == {}

    def test_mixed_reference_images(self):
        """Mix of single and multi-reference per product in same dict."""
        config = PlanogramConfig(
            **_BASE_CONFIG,
            reference_images={
                "ES-C220": ["/path/1.jpg", "/path/2.jpg"],
                "V39-II": "/single.jpg",
            },
        )
        assert isinstance(config.reference_images["ES-C220"], list)
        assert isinstance(config.reference_images["V39-II"], str)

    def test_get_planogram_description_still_works(self):
        """get_planogram_description() still works after extensions."""
        config = PlanogramConfig(
            planogram_config={
                "brand": "Epson",
                "category": "printers",
                "aisle": {"name": "electronics", "category_hints": []},
                "shelves": [],
            },
            roi_detection_prompt="Find the endcap.",
            object_identification_prompt="Identify products.",
            detection_grid=DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS),
        )
        desc = config.get_planogram_description()
        assert desc.brand == "Epson"


class TestIdentifiedProductOutOfPlace:
    """Tests for the out_of_place field on IdentifiedProduct."""

    def test_default_is_false(self):
        """out_of_place defaults to False."""
        p = IdentifiedProduct(product_type="product", confidence=0.9)
        assert p.out_of_place is False

    def test_set_true(self):
        """out_of_place can be set to True."""
        p = IdentifiedProduct(product_type="product", confidence=0.9, out_of_place=True)
        assert p.out_of_place is True

    def test_existing_products_unaffected(self):
        """All existing IdentifiedProduct fields still work normally."""
        p = IdentifiedProduct(
            product_type="printer",
            product_model="ES-C220",
            brand="Epson",
            confidence=0.95,
        )
        assert p.product_type == "printer"
        assert p.product_model == "ES-C220"
        assert p.brand == "Epson"
        assert p.confidence == 0.95
        assert p.out_of_place is False

    def test_out_of_place_serializes(self):
        """out_of_place field appears in model_dump()."""
        p = IdentifiedProduct(product_type="product", confidence=0.9, out_of_place=True)
        data = p.model_dump()
        assert "out_of_place" in data
        assert data["out_of_place"] is True
