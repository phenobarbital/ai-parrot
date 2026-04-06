"""Unit and integration tests for EndcapNoShelvesPromotional planogram type (TASK-596)."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from PIL import Image

from parrot_pipelines.planogram.types.endcap_no_shelves_promotional import EndcapNoShelvesPromotional
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

def _make_image(w: int = 800, h: int = 1000) -> Image.Image:
    """Create a simple test image (tall, like an endcap)."""
    return Image.new("RGB", (w, h), color=(200, 200, 200))


def _make_pipeline() -> MagicMock:
    """Build a mock PlanogramCompliance pipeline."""
    pipeline = MagicMock()
    pipeline.logger = MagicMock()
    pipeline._downscale_image = MagicMock(return_value=_make_image(512, 640))
    pipeline.roi_client = MagicMock()
    return pipeline


def _make_config(planogram_config: dict | None = None) -> MagicMock:
    """Build a mock PlanogramConfig for EndcapNoShelvesPromotional."""
    config = MagicMock()
    config.planogram_config = planogram_config or {
        "brand": "Epson",
        "expected_elements": ["backlit_panel", "lower_poster"],
        "illumination_expected": "ON",
    }
    config.roi_detection_prompt = "Find the promotional endcap area"
    config.object_identification_prompt = None
    config.get_planogram_description.return_value = MagicMock(brand="Epson")
    return config


def _make_detection(label: str, x1=0.1, y1=0.0, x2=0.9, y2=0.5, conf=0.85) -> Detection:
    """Create a mock Detection object."""
    return Detection(
        label=label,
        confidence=conf,
        bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
    )


def _make_identified_product(
    product_type: str,
    visual_features: list | None = None,
    confidence: float = 0.85,
) -> IdentifiedProduct:
    """Create a mock IdentifiedProduct with optional visual_features."""
    return IdentifiedProduct(
        product_type=product_type,
        product_model=product_type,
        confidence=confidence,
        visual_features=visual_features or [],
    )


@pytest.fixture
def mock_pipeline() -> MagicMock:
    return _make_pipeline()


@pytest.fixture
def mock_config() -> MagicMock:
    return _make_config()


@pytest.fixture
def endcap(mock_pipeline, mock_config) -> EndcapNoShelvesPromotional:
    return EndcapNoShelvesPromotional(pipeline=mock_pipeline, config=mock_config)


# ---------------------------------------------------------------------------
# Unit tests: initialisation
# ---------------------------------------------------------------------------

class TestEndcapNoShelvesInit:
    """Tests for EndcapNoShelvesPromotional initialisation."""

    def test_is_abstract_planogram_type(self, endcap):
        """EndcapNoShelvesPromotional must be an AbstractPlanogramType subclass."""
        assert isinstance(endcap, AbstractPlanogramType)

    def test_pipeline_set(self, endcap, mock_pipeline):
        """pipeline attribute is stored."""
        assert endcap.pipeline is mock_pipeline

    def test_config_set(self, endcap, mock_config):
        """config attribute is stored."""
        assert endcap.config is mock_config

    def test_logger_inherited_from_pipeline(self, endcap, mock_pipeline):
        """logger comes from pipeline.logger."""
        assert endcap.logger is mock_pipeline.logger

    def test_get_grid_strategy_returns_no_grid(self, endcap):
        """Default grid strategy is NoGrid (no shelves to split)."""
        strategy = endcap.get_grid_strategy()
        assert isinstance(strategy, NoGrid)


# ---------------------------------------------------------------------------
# Unit tests: detect_objects always returns empty
# ---------------------------------------------------------------------------

class TestEndcapDetectObjects:
    """Tests for detect_objects — must always return ([], [])."""

    @pytest.mark.asyncio
    async def test_returns_empty_products(self, endcap):
        """detect_objects returns empty identified_products list."""
        img = _make_image()
        products, shelves = await endcap.detect_objects(img, None, None)
        assert products == []

    @pytest.mark.asyncio
    async def test_returns_empty_shelf_regions(self, endcap):
        """detect_objects returns empty shelf_regions list."""
        img = _make_image()
        products, shelves = await endcap.detect_objects(img, None, None)
        assert shelves == []

    @pytest.mark.asyncio
    async def test_detect_objects_ignores_roi(self, endcap):
        """detect_objects returns empty regardless of roi value."""
        img = _make_image()
        roi = _make_detection("endcap", x1=0.0, y1=0.0, x2=1.0, y2=1.0)
        products, shelves = await endcap.detect_objects(img, roi, [])
        assert products == []
        assert shelves == []


# ---------------------------------------------------------------------------
# Unit tests: check_planogram_compliance
# ---------------------------------------------------------------------------

class TestEndcapCompliance:
    """Tests for check_planogram_compliance scoring logic."""

    def test_both_zones_present_backlit_on_is_compliant(self, endcap):
        """Backlit ON + both zones present → COMPLIANT, score = 1.0."""
        products = [
            _make_identified_product("backlit_panel", visual_features=["illumination_status: ON"]),
            _make_identified_product("lower_poster"),
        ]
        results = endcap.check_planogram_compliance(products, MagicMock())
        r = results[0]
        assert r.compliance_status == ComplianceStatus.COMPLIANT
        assert r.compliance_score == pytest.approx(1.0, abs=0.001)
        assert "backlit_panel" in r.found_products
        assert "lower_poster" in r.found_products

    def test_backlit_off_penalises_score(self, endcap):
        """Backlit OFF when expected ON → heavy illumination penalty."""
        products = [
            _make_identified_product("backlit_panel", visual_features=["illumination_status: OFF"]),
            _make_identified_product("lower_poster"),
        ]
        results = endcap.check_planogram_compliance(products, MagicMock())
        r = results[0]
        # Backlit present but penalised → score should be lower than full
        assert r.compliance_status != ComplianceStatus.COMPLIANT or r.compliance_score < 1.0
        # Penalty is 100% of backlit weight → only lower_poster score remains
        # total_weight=1.5, poster=0.5, so score = 0.5/1.5 ≈ 0.333
        assert r.compliance_score <= (1.0 / 1.5) + 0.05  # ≤ 0.717

    def test_missing_poster_penalises(self, endcap):
        """Missing lower_poster → score reduced but backlit still contributes."""
        products = [
            _make_identified_product("backlit_panel", visual_features=["illumination_status: ON"]),
        ]
        results = endcap.check_planogram_compliance(products, MagicMock())
        r = results[0]
        assert r.compliance_score > 0.0
        assert r.compliance_score < 1.0
        assert "lower_poster" in r.missing_products

    def test_no_zones_detected_is_missing(self, endcap):
        """No zones detected → MISSING status."""
        results = endcap.check_planogram_compliance([], MagicMock())
        r = results[0]
        assert r.compliance_status == ComplianceStatus.MISSING
        assert r.compliance_score == 0.0

    def test_shelf_level_is_endcap(self, endcap):
        """ComplianceResult shelf_level is 'endcap'."""
        results = endcap.check_planogram_compliance([], MagicMock())
        assert results[0].shelf_level == "endcap"

    def test_returns_list_with_one_result(self, endcap):
        """check_planogram_compliance always returns a list with one item."""
        results = endcap.check_planogram_compliance([], MagicMock())
        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], ComplianceResult)

    def test_illumination_expected_off_no_penalty_when_off(self, mock_pipeline):
        """If illumination_expected=OFF and actual=OFF → no penalty."""
        config = _make_config(
            planogram_config={
                "brand": "Test",
                "expected_elements": ["backlit_panel", "lower_poster"],
                "illumination_expected": "OFF",
            }
        )
        e = EndcapNoShelvesPromotional(pipeline=mock_pipeline, config=config)
        products = [
            _make_identified_product("backlit_panel", visual_features=["illumination_status: OFF"]),
            _make_identified_product("lower_poster"),
        ]
        results = e.check_planogram_compliance(products, MagicMock())
        r = results[0]
        assert r.compliance_score == pytest.approx(1.0, abs=0.001)


# ---------------------------------------------------------------------------
# Integration test: type registration
# ---------------------------------------------------------------------------

class TestEndcapNoShelvesRegistration:
    """Integration tests: verify EndcapNoShelvesPromotional is registered.

    Note: PlanogramCompliance is not imported directly here to avoid the
    transformers-version import chain (gemma4 client).  Registration is
    verified by inspecting ``plan.py`` source directly.
    """

    def test_endcap_in_planogram_types_source(self):
        """plan.py source contains 'endcap_no_shelves_promotional' registration."""
        import os
        plan_path = os.path.join(
            os.path.dirname(__file__),
            "../../packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py",
        )
        plan_path = os.path.normpath(plan_path)
        source = open(plan_path).read()
        assert '"endcap_no_shelves_promotional": EndcapNoShelvesPromotional' in source

    def test_imports_from_types_package(self):
        """EndcapNoShelvesPromotional importable from parrot_pipelines.planogram.types."""
        from parrot_pipelines.planogram.types import EndcapNoShelvesPromotional as ENS
        assert ENS is EndcapNoShelvesPromotional

    def test_both_new_types_in_types_init(self):
        """Both new types are exported from the types package __init__."""
        from parrot_pipelines.planogram.types import ProductCounter, EndcapNoShelvesPromotional
        from parrot_pipelines.planogram.types import ProductOnShelves, GraphicPanelDisplay
        # Original types still present
        assert ProductOnShelves is not None
        assert GraphicPanelDisplay is not None
        # New types added
        assert ProductCounter is not None
        assert EndcapNoShelvesPromotional is not None
