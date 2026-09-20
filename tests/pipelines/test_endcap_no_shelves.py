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
    pipeline.llm = MagicMock()
    pipeline.roi_client = pipeline.llm  # same object until TASK-3432 removes roi_client
    pipeline.resolved_backend = MagicMock(provider="google", model=None)
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
    config.object_identification_prompt = "Identify the endcap zones"  # required since FEAT-574 (TASK-3442)
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
# Unit tests: detect_objects — one product/region per configured zone
#
# TASK-625 (378cc7b69) replaced the original "always ([], [])" behaviour:
# zones now come from ``planogram_config["shelves"]`` (default: backlit_panel
# + lower_poster) and illumination is checked once per image via the LLM.
# ---------------------------------------------------------------------------

_ILLUM_ON = "illumination_status: ON"
_ILLUM_OFF = "illumination_status: OFF"


class TestEndcapDetectObjects:
    """Tests for detect_objects zone synthesis from config."""

    @pytest.mark.asyncio
    async def test_returns_one_product_per_default_zone(self, endcap):
        """Default config yields backlit_panel and lower_poster products."""
        img = _make_image()
        with patch.object(endcap, "_check_illumination", AsyncMock(return_value=_ILLUM_ON)):
            products, _ = await endcap.detect_objects(img, None, None)
        assert [p.shelf_location for p in products] == ["backlit_panel", "lower_poster"]
        assert [p.product_model for p in products] == ["backlit_panel", "lower_poster"]

    @pytest.mark.asyncio
    async def test_returns_one_shelf_region_per_zone(self, endcap):
        """One ShelfRegion is produced per configured zone."""
        img = _make_image()
        with patch.object(endcap, "_check_illumination", AsyncMock(return_value=_ILLUM_ON)):
            _, shelves = await endcap.detect_objects(img, None, None)
        assert [s.level for s in shelves] == ["backlit_panel", "lower_poster"]

    @pytest.mark.asyncio
    async def test_illumination_checked_once_and_seeded(self, endcap):
        """Only the illuminated zone is checked, and its state is seeded."""
        img = _make_image()
        roi = _make_detection("endcap", x1=0.0, y1=0.0, x2=1.0, y2=1.0)
        check = AsyncMock(return_value=_ILLUM_OFF)
        with patch.object(endcap, "_check_illumination", check):
            products, _ = await endcap.detect_objects(img, roi, [])
        check.assert_awaited_once()
        assert products[0].visual_features == [_ILLUM_OFF]
        assert products[1].visual_features == []

    @pytest.mark.asyncio
    async def test_illumination_check_failure_does_not_crash(self, endcap):
        """A failed LLM illumination check (None) leaves features empty."""
        img = _make_image()
        with patch.object(endcap, "_check_illumination", AsyncMock(return_value=None)):
            products, _ = await endcap.detect_objects(img, None, None)
        assert len(products) == 2
        assert products[0].visual_features == []


# ---------------------------------------------------------------------------
# Unit tests: check_planogram_compliance — one ComplianceResult per zone
# ---------------------------------------------------------------------------


def _description(threshold: float = 0.8) -> MagicMock:
    """Planogram description stub with a real numeric compliance threshold."""
    desc = MagicMock()
    desc.global_compliance_threshold = threshold
    return desc


def _zone_product(zone: str, visual_features: list | None = None) -> IdentifiedProduct:
    """IdentifiedProduct placed on *zone* (matched by ``shelf_location``)."""
    product = _make_identified_product(zone, visual_features=visual_features)
    product.shelf_location = zone
    return product


class TestEndcapCompliance:
    """Tests for check_planogram_compliance scoring logic."""

    @staticmethod
    def _by_level(results):
        return {r.shelf_level: r for r in results}

    def test_both_zones_present_backlit_on_is_compliant(self, endcap):
        """Backlit ON + both zones present → every zone COMPLIANT, score = 1.0."""
        products = [
            _zone_product("backlit_panel", visual_features=[_ILLUM_ON]),
            _zone_product("lower_poster"),
        ]
        results = self._by_level(endcap.check_planogram_compliance(products, _description()))
        for level in ("backlit_panel", "lower_poster"):
            assert results[level].compliance_status == ComplianceStatus.COMPLIANT
            assert results[level].compliance_score == pytest.approx(1.0, abs=0.001)
            assert level in results[level].found_products

    def test_backlit_off_penalises_score(self, endcap):
        """Backlit OFF when expected ON → full illumination penalty on that zone."""
        products = [
            _zone_product("backlit_panel", visual_features=[_ILLUM_OFF]),
            _zone_product("lower_poster"),
        ]
        results = self._by_level(endcap.check_planogram_compliance(products, _description()))
        backlit = results["backlit_panel"]
        assert backlit.compliance_status == ComplianceStatus.NON_COMPLIANT
        assert backlit.compliance_score == pytest.approx(0.0, abs=0.001)
        assert any("backlight OFF" in m for m in backlit.missing_products)
        assert results["lower_poster"].compliance_status == ComplianceStatus.COMPLIANT

    def test_missing_poster_penalises(self, endcap):
        """Missing lower_poster → that zone MISSING; backlit zone unaffected."""
        products = [_zone_product("backlit_panel", visual_features=[_ILLUM_ON])]
        results = self._by_level(endcap.check_planogram_compliance(products, _description()))
        poster = results["lower_poster"]
        assert poster.compliance_status == ComplianceStatus.MISSING
        assert poster.compliance_score == 0.0
        assert "lower_poster" in poster.missing_products
        assert results["backlit_panel"].compliance_score == pytest.approx(1.0, abs=0.001)

    def test_no_zones_detected_is_missing(self, endcap):
        """No zones detected → every zone MISSING with score 0."""
        results = endcap.check_planogram_compliance([], _description())
        for r in results:
            assert r.compliance_status == ComplianceStatus.MISSING
            assert r.compliance_score == 0.0

    def test_shelf_levels_are_config_zones(self, endcap):
        """ComplianceResult shelf_level values are the configured zone levels."""
        results = endcap.check_planogram_compliance([], _description())
        assert [r.shelf_level for r in results] == ["backlit_panel", "lower_poster"]

    def test_returns_one_result_per_zone(self, endcap):
        """check_planogram_compliance returns one ComplianceResult per zone."""
        results = endcap.check_planogram_compliance([], _description())
        assert isinstance(results, list)
        assert len(results) == 2
        assert all(isinstance(r, ComplianceResult) for r in results)

    def test_illumination_expected_off_no_penalty_when_off(self, mock_pipeline):
        """If the zone expects OFF and actual=OFF → no penalty."""
        config = _make_config(
            planogram_config={
                "brand": "Test",
                "shelves": [
                    {
                        "level": "backlit_panel",
                        "products": [{"name": "backlit_panel", "visual_features": [_ILLUM_OFF]}],
                    },
                    {"level": "lower_poster", "products": [{"name": "lower_poster"}]},
                ],
            }
        )
        e = EndcapNoShelvesPromotional(pipeline=mock_pipeline, config=config)
        products = [
            _zone_product("backlit_panel", visual_features=[_ILLUM_OFF]),
            _zone_product("lower_poster"),
        ]
        results = self._by_level(e.check_planogram_compliance(products, _description()))
        assert results["backlit_panel"].compliance_score == pytest.approx(1.0, abs=0.001)
        assert results["backlit_panel"].compliance_status == ComplianceStatus.COMPLIANT


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
