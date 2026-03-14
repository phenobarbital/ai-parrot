"""Tests for the Planogram Compliance Modular composable pattern (FEAT-048)."""
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.pipelines.planogram.types.abstract import AbstractPlanogramType
from parrot.pipelines.planogram.types.product_on_shelves import ProductOnShelves
from parrot.pipelines.planogram.plan import PlanogramCompliance
from parrot.pipelines.models import PlanogramConfig, EndcapGeometry
from parrot.models.detections import (
    DetectionBox,
    ShelfRegion,
    IdentifiedProduct,
)
from parrot.models.compliance import ComplianceResult, ComplianceStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_planogram_config():
    """Minimal PlanogramConfig for testing."""
    return {
        "brand": "TestBrand",
        "category": "TestCategory",
        "aisle": {"name": "Electronics > Test", "lighting_conditions": "normal"},
        "shelves": [
            {
                "level": "header",
                "height_ratio": 0.2,
                "products": [
                    {
                        "name": "TestBrand Logo",
                        "product_type": "promotional_graphic",
                        "mandatory": True,
                        "visual_features": ["illuminated logo"],
                    }
                ],
                "allow_extra_products": False,
                "compliance_threshold": 0.9,
            },
            {
                "level": "main_shelf",
                "height_ratio": 0.6,
                "products": [
                    {
                        "name": "Product A",
                        "product_type": "product",
                        "mandatory": True,
                    },
                    {
                        "name": "Product B",
                        "product_type": "product",
                        "mandatory": True,
                    },
                ],
                "allow_extra_products": False,
                "compliance_threshold": 0.8,
            },
            {
                "level": "bottom",
                "height_ratio": 0.2,
                "products": [
                    {
                        "name": "Promo Card",
                        "product_type": "promotional_graphic",
                    }
                ],
                "allow_extra_products": True,
                "compliance_threshold": 0.7,
            },
        ],
    }


@pytest.fixture
def planogram_config_obj(sample_planogram_config):
    """PlanogramConfig Pydantic model instance."""
    return PlanogramConfig(
        config_name="test_planogram",
        planogram_type="product_on_shelves",
        planogram_config=sample_planogram_config,
        roi_detection_prompt="Detect the endcap for {brand}.",
        object_identification_prompt="Identify products.",
    )


@pytest.fixture
def mock_pipeline(planogram_config_obj):
    """A mock PlanogramCompliance pipeline for composable tests."""
    pipeline = MagicMock(spec=PlanogramCompliance)
    pipeline.logger = logging.getLogger("test.planogram")
    pipeline.planogram_config = planogram_config_obj
    pipeline.reference_images = {}
    pipeline.roi_client = MagicMock()
    pipeline.llm = MagicMock()
    pipeline._json = MagicMock()
    pipeline._downscale_image = MagicMock()
    pipeline.left_margin_ratio = 0.01
    pipeline.right_margin_ratio = 0.03
    return pipeline


@pytest.fixture
def product_on_shelves(mock_pipeline, planogram_config_obj):
    """ProductOnShelves composable instance."""
    return ProductOnShelves(pipeline=mock_pipeline, config=planogram_config_obj)


@pytest.fixture
def sample_shelf_regions():
    """Three sample shelf regions for assignment tests."""
    return [
        ShelfRegion(
            shelf_id="virtual_header",
            level="header",
            bbox=DetectionBox(x1=100, y1=0, x2=500, y2=100, confidence=1.0),
        ),
        ShelfRegion(
            shelf_id="virtual_main_shelf",
            level="main_shelf",
            bbox=DetectionBox(x1=100, y1=100, x2=500, y2=400, confidence=1.0),
        ),
        ShelfRegion(
            shelf_id="virtual_bottom",
            level="bottom",
            bbox=DetectionBox(x1=100, y1=400, x2=500, y2=500, confidence=1.0),
        ),
    ]


@pytest.fixture
def sample_db_row(sample_planogram_config):
    """Sample DB row for handler hydration tests."""
    return {
        "planogram_id": 1,
        "config_name": "test_config",
        "planogram_type": "product_on_shelves",
        "planogram_config": sample_planogram_config,
        "roi_detection_prompt": "Detect...",
        "object_identification_prompt": "Identify...",
        "reference_images": {},
        "confidence_threshold": 0.25,
        "detection_model": "yolo11l.pt",
        "aspect_ratio": 1.35,
        "left_margin_ratio": 0.01,
        "right_margin_ratio": 0.03,
        "top_margin_ratio": 0.02,
        "bottom_margin_ratio": 0.05,
        "inter_shelf_padding": 0.02,
        "width_margin_percent": 0.25,
        "height_margin_percent": 0.30,
        "top_margin_percent": 0.05,
        "side_margin_percent": 0.05,
        "is_active": True,
    }


# ===================================================================
# 1. ABC Contract Tests
# ===================================================================

class TestAbstractPlanogramType:

    def test_cannot_instantiate_directly(self, mock_pipeline, planogram_config_obj):
        """AbstractPlanogramType is ABC and cannot be instantiated."""
        with pytest.raises(TypeError, match="abstract"):
            AbstractPlanogramType(pipeline=mock_pipeline, config=planogram_config_obj)

    def test_abstract_methods_enforced(self, mock_pipeline, planogram_config_obj):
        """Subclass missing abstract methods raises TypeError."""
        class IncompleteType(AbstractPlanogramType):
            async def compute_roi(self, img):
                pass
            # Missing: detect_objects_roi, detect_objects, check_planogram_compliance

        with pytest.raises(TypeError, match="abstract"):
            IncompleteType(pipeline=mock_pipeline, config=planogram_config_obj)

    def test_default_render_colors(self, mock_pipeline, planogram_config_obj):
        """get_render_colors returns dict with expected keys."""
        class CompleteType(AbstractPlanogramType):
            async def compute_roi(self, img):
                pass
            async def detect_objects_roi(self, img, roi):
                pass
            async def detect_objects(self, img, roi, m):
                pass
            def check_planogram_compliance(self, p, d):
                pass

        t = CompleteType(pipeline=mock_pipeline, config=planogram_config_obj)
        colors = t.get_render_colors()
        assert isinstance(colors, dict)
        expected_keys = {"roi", "detection", "product", "compliant", "non_compliant"}
        assert set(colors.keys()) == expected_keys
        # Values should be RGB tuples
        for k, v in colors.items():
            assert isinstance(v, tuple) and len(v) == 3, f"{k} is not an RGB tuple"


# ===================================================================
# 2. Registry & Delegation Tests
# ===================================================================

class TestPlanogramComplianceRegistry:

    def test_registry_contains_product_on_shelves(self):
        """Registry has product_on_shelves entry."""
        assert "product_on_shelves" in PlanogramCompliance._PLANOGRAM_TYPES
        assert PlanogramCompliance._PLANOGRAM_TYPES["product_on_shelves"] is ProductOnShelves

    @patch("parrot.pipelines.planogram.plan.AbstractPipeline.__init__", return_value=None)
    def test_resolves_product_on_shelves(self, mock_init, planogram_config_obj):
        """PlanogramCompliance resolves ProductOnShelves from planogram_type."""
        # Mock AbstractPipeline init to avoid LLM setup
        pc = PlanogramCompliance.__new__(PlanogramCompliance)
        pc.logger = logging.getLogger("test")
        pc.planogram_config = planogram_config_obj
        pc.reference_images = {}
        pc.left_margin_ratio = 0.01
        pc.right_margin_ratio = 0.03
        # Manually resolve type handler
        ptype = planogram_config_obj.planogram_type
        composable_cls = PlanogramCompliance._PLANOGRAM_TYPES[ptype]
        pc._type_handler = composable_cls(pipeline=pc, config=planogram_config_obj)
        assert isinstance(pc._type_handler, ProductOnShelves)

    def test_unknown_type_raises_valueerror(self):
        """Unknown planogram_type raises ValueError with available types."""
        config = PlanogramConfig(
            planogram_type="nonexistent_type",
            planogram_config={},
            roi_detection_prompt="",
            object_identification_prompt="",
        )
        with pytest.raises(ValueError, match="Unknown planogram_type 'nonexistent_type'"):
            PlanogramCompliance(planogram_config=config)

    def test_default_type_is_product_on_shelves(self):
        """Missing planogram_type defaults to product_on_shelves."""
        config = PlanogramConfig(
            planogram_config={},
            roi_detection_prompt="",
            object_identification_prompt="",
        )
        assert config.planogram_type == "product_on_shelves"


# ===================================================================
# 3. PlanogramConfig Tests
# ===================================================================

class TestPlanogramConfigType:

    def test_planogram_type_field_exists(self):
        """PlanogramConfig has planogram_type field."""
        config = PlanogramConfig(
            planogram_config={},
            roi_detection_prompt="",
            object_identification_prompt="",
        )
        assert hasattr(config, "planogram_type")

    def test_planogram_type_default(self):
        """Default planogram_type is product_on_shelves."""
        config = PlanogramConfig(
            planogram_config={},
            roi_detection_prompt="",
            object_identification_prompt="",
        )
        assert config.planogram_type == "product_on_shelves"

    def test_planogram_type_explicit(self):
        """Explicit planogram_type is stored correctly."""
        config = PlanogramConfig(
            planogram_type="tv_wall",
            planogram_config={},
            roi_detection_prompt="",
            object_identification_prompt="",
        )
        assert config.planogram_type == "tv_wall"

    def test_planogram_type_serialization(self):
        """planogram_type survives serialization round-trip."""
        config = PlanogramConfig(
            planogram_type="ink_wall",
            planogram_config={},
            roi_detection_prompt="",
            object_identification_prompt="",
        )
        data = config.model_dump()
        assert data["planogram_type"] == "ink_wall"


# ===================================================================
# 4. ProductOnShelves Tests
# ===================================================================

class TestProductOnShelves:

    def test_implements_contract(self, product_on_shelves):
        """ProductOnShelves can be instantiated (all abstract methods implemented)."""
        assert isinstance(product_on_shelves, AbstractPlanogramType)
        assert isinstance(product_on_shelves, ProductOnShelves)

    def test_pipeline_reference(self, product_on_shelves, mock_pipeline):
        """Composable stores pipeline reference correctly."""
        assert product_on_shelves.pipeline is mock_pipeline

    def test_config_reference(self, product_on_shelves, planogram_config_obj):
        """Composable stores config reference correctly."""
        assert product_on_shelves.config is planogram_config_obj

    def test_virtual_shelves_generation(self, product_on_shelves):
        """_generate_virtual_shelves produces correct number of shelves."""
        roi_bbox = DetectionBox(x1=100, y1=100, x2=900, y2=900, confidence=1.0)
        image_size = (1000, 1000)
        planogram_desc = product_on_shelves.config.get_planogram_description()

        shelves = product_on_shelves._generate_virtual_shelves(
            roi_bbox, image_size, planogram_desc
        )
        assert len(shelves) == 3  # header, main_shelf, bottom
        assert shelves[0].level == "header"
        assert shelves[1].level == "main_shelf"
        assert shelves[2].level == "bottom"

    def test_assign_products_to_shelves(self, product_on_shelves, sample_shelf_regions):
        """Products are assigned to shelves based on spatial position."""
        products = [
            IdentifiedProduct(
                detection_box=DetectionBox(x1=200, y1=50, x2=300, y2=90, confidence=0.9),
                product_model="Logo",
                confidence=0.9,
                product_type="promotional_graphic",
            ),
            IdentifiedProduct(
                detection_box=DetectionBox(x1=200, y1=200, x2=300, y2=300, confidence=0.9),
                product_model="Product A",
                confidence=0.9,
                product_type="product",
            ),
            IdentifiedProduct(
                detection_box=DetectionBox(x1=200, y1=420, x2=300, y2=480, confidence=0.9),
                product_model="Promo",
                confidence=0.9,
                product_type="promotional_graphic",
            ),
        ]

        product_on_shelves._assign_products_to_shelves(products, sample_shelf_regions)

        assert products[0].shelf_location == "header"
        assert products[1].shelf_location == "main_shelf"
        assert products[2].shelf_location == "bottom"

    def test_default_shelf_configs(self, product_on_shelves):
        """_get_default_shelf_configs returns 3 shelves."""
        defaults = product_on_shelves._get_default_shelf_configs()
        assert len(defaults) == 3
        assert defaults[0]["level"] == "header"
        assert defaults[1]["level"] == "middle"
        assert defaults[2]["level"] == "bottom"

    def test_looks_like_box(self, product_on_shelves):
        """_looks_like_box detects box-like visual features."""
        assert product_on_shelves._looks_like_box(["product packaging visible"]) is True
        assert product_on_shelves._looks_like_box(["cardboard box"]) is True
        assert product_on_shelves._looks_like_box(["a box of ink"]) is True
        assert product_on_shelves._looks_like_box(["active display"]) is False
        assert product_on_shelves._looks_like_box(None) is False
        assert product_on_shelves._looks_like_box([]) is False

    def test_normalize_ocr_text(self, product_on_shelves):
        """_normalize_ocr_text cleans OCR strings."""
        result = product_on_shelves._normalize_ocr_text("HISENSE™")
        assert "hisense" in result
        assert product_on_shelves._normalize_ocr_text("") == ""
        result = product_on_shelves._normalize_ocr_text("Hello—World")
        assert "hello" in result
        assert "world" in result

    def test_calculate_visual_feature_match(self, product_on_shelves):
        """Visual feature matching scores correctly."""
        # Perfect match
        score = product_on_shelves._calculate_visual_feature_match(
            ["illuminated logo"], ["illuminated logo on display"]
        )
        assert score > 0.0

        # No match
        score = product_on_shelves._calculate_visual_feature_match(
            ["tiger image"], ["blue background"]
        )
        assert score == 0.0

        # Empty expected = 1.0
        assert product_on_shelves._calculate_visual_feature_match([], ["anything"]) == 1.0

        # Empty detected = 0.0
        assert product_on_shelves._calculate_visual_feature_match(["something"], []) == 0.0

    def test_base_model_from_str(self, product_on_shelves):
        """_base_model_from_str extracts model identifiers."""
        assert product_on_shelves._base_model_from_str("ET-2800 Printer") == "et-2800"
        assert product_on_shelves._base_model_from_str("", brand="test") == ""

    def test_canonical_keys(self, product_on_shelves):
        """Canonical key extraction for expected and found products."""
        # Expected key
        sp = MagicMock()
        sp.product_type = "product"
        sp.name = "ET-2800"
        ek = product_on_shelves._canonical_expected_key(sp, brand="epson")
        assert ek[0] == "product"

        # Found key
        p = MagicMock()
        p.product_type = "product"
        p.product_model = "ET-2800 Printer"
        p.confidence = 0.9
        p.visual_features = None
        fk = product_on_shelves._canonical_found_key(p, brand="epson")
        assert fk[0] == "product"
        assert isinstance(fk[2], float)


# ===================================================================
# 5. Rendering Color Tests
# ===================================================================

class TestRenderColors:

    def test_product_on_shelves_default_colors(self, product_on_shelves):
        """ProductOnShelves returns default color scheme."""
        colors = product_on_shelves.get_render_colors()
        assert "roi" in colors
        assert "compliant" in colors
        assert colors["roi"] == (0, 255, 0)


# ===================================================================
# 6. Handler Hydration Tests
# ===================================================================

class TestHandlerHydration:

    def test_build_planogram_config_includes_type(self, sample_db_row):
        """_build_planogram_config includes planogram_type from DB row."""
        from parrot.handlers.planogram_compliance import PlanogramComplianceHandler

        handler = MagicMock(spec=PlanogramComplianceHandler)
        handler._build_planogram_config = PlanogramComplianceHandler._build_planogram_config.__get__(handler)
        handler.logger = logging.getLogger("test")

        config = handler._build_planogram_config(sample_db_row)
        assert config.planogram_type == "product_on_shelves"

    def test_build_planogram_config_default_type(self, sample_db_row):
        """DB row without planogram_type defaults to product_on_shelves."""
        from parrot.handlers.planogram_compliance import PlanogramComplianceHandler

        row = {k: v for k, v in sample_db_row.items() if k != "planogram_type"}
        handler = MagicMock(spec=PlanogramComplianceHandler)
        handler._build_planogram_config = PlanogramComplianceHandler._build_planogram_config.__get__(handler)
        handler.logger = logging.getLogger("test")

        config = handler._build_planogram_config(row)
        assert config.planogram_type == "product_on_shelves"


# ===================================================================
# 7. Integration / Backwards Compatibility
# ===================================================================

class TestBackwardsCompatibility:

    def test_config_without_type_uses_default(self):
        """Config without planogram_type uses product_on_shelves default."""
        config = PlanogramConfig(
            planogram_config={"brand": "Test", "shelves": []},
            roi_detection_prompt="",
            object_identification_prompt="",
        )
        assert config.planogram_type == "product_on_shelves"
