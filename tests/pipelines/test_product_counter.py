"""Unit and integration tests for ProductCounter planogram type (TASK-596)."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from PIL import Image

from parrot_pipelines.planogram.types.product_counter import ProductCounter, _DEFAULT_WEIGHTS
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType
from parrot_pipelines.planogram.grid.strategy import NoGrid
from parrot.models.detections import (
    Detection,
    BoundingBox,
    Detections,
    IdentifiedProduct,
    DetectionBox,
    ShelfRegion,
)
from parrot.models.compliance import ComplianceResult, ComplianceStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_image(w: int = 800, h: int = 600) -> Image.Image:
    """Create a simple test image."""
    return Image.new("RGB", (w, h), color=(200, 200, 200))


def _make_pipeline() -> MagicMock:
    """Build a mock PlanogramCompliance pipeline."""
    pipeline = MagicMock()
    pipeline.logger = MagicMock()
    pipeline._downscale_image = MagicMock(return_value=_make_image(512, 384))
    pipeline.roi_client = MagicMock()
    return pipeline


def _make_config(planogram_config: dict | None = None) -> MagicMock:
    """Build a mock PlanogramConfig."""
    config = MagicMock()
    config.planogram_config = planogram_config or {
        "brand": "Epson",
        "expected_elements": ["product", "promotional_background", "information_label"],
    }
    config.roi_detection_prompt = "Find the counter display area"
    config.object_identification_prompt = "Identify elements on counter"
    config.get_planogram_description.return_value = MagicMock(brand="Epson")
    return config


def _make_detection(label: str, x1=0.1, y1=0.1, x2=0.9, y2=0.9, conf=0.85) -> Detection:
    """Create a mock Detection object."""
    return Detection(
        label=label,
        confidence=conf,
        bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
    )


def _make_identified_product(product_type: str, confidence: float = 0.85) -> IdentifiedProduct:
    """Create a mock IdentifiedProduct."""
    return IdentifiedProduct(
        product_type=product_type,
        product_model=product_type,
        confidence=confidence,
        visual_features=[],
    )


@pytest.fixture
def mock_pipeline() -> MagicMock:
    return _make_pipeline()


@pytest.fixture
def mock_config() -> MagicMock:
    return _make_config()


@pytest.fixture
def counter(mock_pipeline, mock_config) -> ProductCounter:
    return ProductCounter(pipeline=mock_pipeline, config=mock_config)


# ---------------------------------------------------------------------------
# Unit tests: initialisation
# ---------------------------------------------------------------------------

class TestProductCounterInit:
    """Tests for ProductCounter initialisation."""

    def test_is_abstract_planogram_type(self, counter):
        """ProductCounter must be an AbstractPlanogramType subclass."""
        assert isinstance(counter, AbstractPlanogramType)

    def test_pipeline_set(self, counter, mock_pipeline):
        """pipeline attribute is stored from constructor."""
        assert counter.pipeline is mock_pipeline

    def test_config_set(self, counter, mock_config):
        """config attribute is stored from constructor."""
        assert counter.config is mock_config

    def test_logger_inherited_from_pipeline(self, counter, mock_pipeline):
        """logger comes from pipeline.logger."""
        assert counter.logger is mock_pipeline.logger

    def test_get_grid_strategy_returns_no_grid(self, counter):
        """Default grid strategy for ProductCounter is NoGrid."""
        strategy = counter.get_grid_strategy()
        assert isinstance(strategy, NoGrid)


# ---------------------------------------------------------------------------
# Unit tests: check_planogram_compliance
# ---------------------------------------------------------------------------

class TestProductCounterCompliance:
    """Tests for check_planogram_compliance scoring logic."""

    def test_all_elements_present_is_compliant(self, counter):
        """All three elements present → COMPLIANT with score near 1.0."""
        products = [
            _make_identified_product("product"),
            _make_identified_product("promotional_background"),
            _make_identified_product("information_label"),
        ]
        results = counter.check_planogram_compliance(products, MagicMock())
        assert len(results) == 1
        r = results[0]
        assert r.compliance_status == ComplianceStatus.COMPLIANT
        assert r.compliance_score == pytest.approx(1.0, abs=0.001)
        assert "product" in r.found_products
        assert "promotional_background" in r.found_products
        assert "information_label" in r.found_products
        assert r.missing_products == []

    def test_missing_label_penalises_but_not_zero(self, counter):
        """Missing information_label reduces score but does not zero it."""
        products = [
            _make_identified_product("product"),
            _make_identified_product("promotional_background"),
        ]
        results = counter.check_planogram_compliance(products, MagicMock())
        r = results[0]
        assert r.compliance_status in (ComplianceStatus.NON_COMPLIANT, ComplianceStatus.COMPLIANT)
        assert r.compliance_score > 0.0
        assert r.compliance_score < 1.0
        assert "information_label" in r.missing_products

    def test_missing_product_heavily_penalises(self, counter):
        """Missing product (weight=1.0) results in low compliance score."""
        products = [
            _make_identified_product("promotional_background"),
            _make_identified_product("information_label"),
        ]
        results = counter.check_planogram_compliance(products, MagicMock())
        r = results[0]
        assert r.compliance_status == ComplianceStatus.NON_COMPLIANT
        assert r.compliance_score < 0.5
        assert "product" in r.missing_products

    def test_missing_promo_background_moderate_penalty(self, counter):
        """Missing promotional_background (weight=0.5) produces moderate penalty."""
        products = [
            _make_identified_product("product"),
            _make_identified_product("information_label"),
        ]
        results = counter.check_planogram_compliance(products, MagicMock())
        r = results[0]
        assert r.compliance_score > 0.0
        assert r.compliance_score < 1.0
        assert "promotional_background" in r.missing_products

    def test_no_elements_detected_is_missing(self, counter):
        """No elements detected → compliance_status MISSING."""
        results = counter.check_planogram_compliance([], MagicMock())
        r = results[0]
        assert r.compliance_status == ComplianceStatus.MISSING
        assert r.compliance_score == 0.0

    def test_shelf_level_is_counter(self, counter):
        """ComplianceResult shelf_level is 'counter'."""
        results = counter.check_planogram_compliance([], MagicMock())
        assert results[0].shelf_level == "counter"

    def test_custom_weights_respected(self, mock_pipeline):
        """Custom scoring_weights from planogram_config are used."""
        config = _make_config(
            planogram_config={
                "brand": "Test",
                "scoring_weights": {
                    "product": 2.0,
                    "promotional_background": 0.1,
                    "information_label": 0.1,
                },
            }
        )
        c = ProductCounter(pipeline=mock_pipeline, config=config)
        # Only product present
        products = [_make_identified_product("product")]
        results = c.check_planogram_compliance(products, MagicMock())
        r = results[0]
        total = 2.0 + 0.1 + 0.1
        expected_score = 2.0 / total
        assert r.compliance_score == pytest.approx(expected_score, abs=0.001)

    def test_returns_list_with_one_result(self, counter):
        """check_planogram_compliance always returns a list with exactly one item."""
        results = counter.check_planogram_compliance([], MagicMock())
        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], ComplianceResult)


# ---------------------------------------------------------------------------
# Unit tests: detect_objects
# ---------------------------------------------------------------------------

class TestProductCounterDetectObjects:
    """Tests for detect_objects."""

    @pytest.mark.asyncio
    async def test_returns_empty_shelf_regions(self, counter):
        """detect_objects always returns an empty ShelfRegion list."""
        img = _make_image()
        mock_roi = _make_detection("counter")
        mock_elements = [
            _make_detection("product"),
            _make_detection("promotional_background"),
        ]
        products, shelves = await counter.detect_objects(img, mock_roi, mock_elements)
        assert shelves == []

    @pytest.mark.asyncio
    async def test_returns_identified_products_from_macro_objects(self, counter):
        """detect_objects maps macro element Detections to IdentifiedProduct."""
        img = _make_image()
        mock_roi = _make_detection("counter", x1=0.0, y1=0.0, x2=1.0, y2=1.0)
        macro_objects = [
            _make_detection("product", conf=0.9),
            _make_detection("promotional_background", conf=0.8),
        ]
        products, shelves = await counter.detect_objects(img, mock_roi, macro_objects)
        assert len(products) == 2
        types = {p.product_type for p in products}
        assert "product" in types
        assert "promotional_background" in types

    @pytest.mark.asyncio
    async def test_detect_objects_no_roi_returns_empty(self, counter):
        """detect_objects with None ROI and None macro_objects returns empty."""
        img = _make_image()
        # When roi is None and macro_objects is None, no LLM call is made
        products, shelves = await counter.detect_objects(img, None, [])
        assert shelves == []
        assert products == []


# ---------------------------------------------------------------------------
# Integration test: type registration
# ---------------------------------------------------------------------------

class TestProductCounterRegistration:
    """Integration tests: verify ProductCounter is registered in PlanogramCompliance."""

    def test_product_counter_in_planogram_types(self):
        """PlanogramCompliance._PLANOGRAM_TYPES contains 'product_counter'."""
        from parrot_pipelines.planogram.plan import PlanogramCompliance
        assert "product_counter" in PlanogramCompliance._PLANOGRAM_TYPES
        assert PlanogramCompliance._PLANOGRAM_TYPES["product_counter"] is ProductCounter

    def test_imports_from_types_package(self):
        """ProductCounter importable from parrot_pipelines.planogram.types."""
        from parrot_pipelines.planogram.types import ProductCounter as PC
        assert PC is ProductCounter
