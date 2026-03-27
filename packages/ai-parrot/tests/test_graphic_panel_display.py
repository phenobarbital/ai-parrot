"""Unit tests for GraphicPanelDisplay planogram type composable.

Tests cover:
- Zone detection (all present / missing zone)
- Illumination check (OFF pass, OFF fail, ON pass)
- Configurable illumination penalty
- Text requirement evaluation (pass / fail)
- No fact-tag / product-counting logic
- Type registration in _PLANOGRAM_TYPES
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

from parrot.pipelines.planogram.types.graphic_panel_display import GraphicPanelDisplay
from parrot.pipelines.planogram.plan import PlanogramCompliance
from parrot.models.compliance import ComplianceStatus


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_pipeline_mock():
    """Mock PlanogramCompliance pipeline with logger."""
    mock = MagicMock()
    mock.logger = MagicMock()
    return mock


def _make_shelf_product(
    name: str,
    visual_features=None,
    text_requirements=None,
    illumination_penalty=None,
):
    """Build a minimal shelf-product config mock."""
    p = MagicMock()
    p.name = name
    p.product_type = "graphic_zone"
    p.visual_features = visual_features or []
    p.text_requirements = text_requirements or []
    if illumination_penalty is not None:
        p.illumination_penalty = illumination_penalty
    else:
        # Mimic "attribute not set" so getattr returns None
        del p.illumination_penalty
    return p


def _make_shelf_cfg(level: str, products, illumination_penalty=None, compliance_threshold=0.8):
    """Build a minimal shelf config mock."""
    s = MagicMock()
    s.level = level
    s.products = products
    s.compliance_threshold = compliance_threshold
    if illumination_penalty is not None:
        s.illumination_penalty = illumination_penalty
    else:
        del s.illumination_penalty
    return s


def _make_planogram_description(shelves, brand="Epson", global_compliance_threshold=0.8):
    """Build a minimal planogram description mock."""
    pd = MagicMock()
    pd.brand = brand
    pd.shelves = shelves
    pd.global_compliance_threshold = global_compliance_threshold
    return pd


def _make_identified_product(name: str, shelf_level: str, confidence=1.0, visual_features=None):
    """Build an IdentifiedProduct mock."""
    p = MagicMock()
    p.product_model = name
    p.product_type = "graphic_zone"
    p.shelf_location = shelf_level
    p.confidence = confidence
    p.visual_features = visual_features or []
    p.detection_box = None
    p.brand = "Epson"
    return p


def _make_config(shelves):
    """Build a PlanogramConfig mock."""
    cfg = MagicMock()
    cfg.roi_detection_prompt = "Find zones"
    cfg.get_planogram_description = MagicMock(return_value=_make_planogram_description(shelves))
    return cfg


def _make_type(pipeline_mock=None, config_mock=None, shelves=None):
    """Instantiate GraphicPanelDisplay with mocks."""
    shelves = shelves or []
    pipeline = pipeline_mock or _make_pipeline_mock()
    config = config_mock or _make_config(shelves)
    return GraphicPanelDisplay(pipeline=pipeline, config=config)


# ---------------------------------------------------------------------------
# Tests: zone detection
# ---------------------------------------------------------------------------

class TestZoneDetection:
    """check_planogram_compliance — zone presence logic."""

    def test_zone_detection_all_present(self):
        """All expected zones detected → compliance_score == 1.0 for each shelf."""
        header_prod = _make_shelf_product("Epson_Top_Not_Backlit")
        middle_prod = _make_shelf_product("Epson_Comparison_Table")
        bottom_prod = _make_shelf_product("Epson_Base_Special_Offer")

        shelves = [
            _make_shelf_cfg("header", [header_prod]),
            _make_shelf_cfg("middle", [middle_prod]),
            _make_shelf_cfg("bottom", [bottom_prod]),
        ]
        planogram_description = _make_planogram_description(shelves)

        identified = [
            _make_identified_product("Epson_Top_Not_Backlit", "header", confidence=0.95),
            _make_identified_product("Epson_Comparison_Table", "middle", confidence=0.90),
            _make_identified_product("Epson_Base_Special_Offer", "bottom", confidence=0.88),
        ]

        gp = _make_type(shelves=shelves)
        results = gp.check_planogram_compliance(identified, planogram_description)

        assert len(results) == 3
        for r in results:
            assert r.compliance_score == pytest.approx(1.0)
            assert r.compliance_status == ComplianceStatus.COMPLIANT

    def test_zone_detection_missing_zone(self):
        """Missing mandatory zone → non-compliant with score 0.0."""
        header_prod = _make_shelf_product("Epson_Top_Not_Backlit")
        shelves = [_make_shelf_cfg("header", [header_prod])]
        planogram_description = _make_planogram_description(shelves)

        # No identified products for this shelf
        identified = []

        gp = _make_type(shelves=shelves)
        results = gp.check_planogram_compliance(identified, planogram_description)

        assert len(results) == 1
        assert results[0].compliance_score == pytest.approx(0.0)
        assert results[0].compliance_status == ComplianceStatus.MISSING
        assert "Epson_Top_Not_Backlit" in results[0].missing_products


# ---------------------------------------------------------------------------
# Tests: illumination check
# ---------------------------------------------------------------------------

class TestIlluminationCheck:
    """Illumination state compliance and configurable penalty."""

    def _run(self, expected_state: str, detected_state: str, penalty=None) -> float:
        """Helper: build a single-shelf planogram and return compliance_score."""
        prod_cfg = _make_shelf_product(
            "Epson_Top_Not_Backlit",
            visual_features=[f"illumination_status: {expected_state}"],
        )
        shelf_cfg = _make_shelf_cfg("header", [prod_cfg])
        if penalty is not None:
            shelf_cfg.illumination_penalty = penalty

        planogram_description = _make_planogram_description([shelf_cfg])

        identified = [
            _make_identified_product(
                "Epson_Top_Not_Backlit",
                "header",
                confidence=0.95,
                visual_features=[f"illumination_status: {detected_state}"],
            )
        ]

        gp = _make_type(shelves=[shelf_cfg])
        results = gp.check_planogram_compliance(identified, planogram_description)
        return results[0].compliance_score

    def test_illumination_check_off_pass(self):
        """Zone expected OFF, detected OFF → no penalty applied."""
        score = self._run("OFF", "OFF")
        assert score == pytest.approx(1.0)

    def test_illumination_check_off_fail(self):
        """Zone expected OFF but detected ON → default penalty=1.0 → score=0."""
        score = self._run("OFF", "ON")
        assert score == pytest.approx(0.0)

    def test_illumination_check_on_pass(self):
        """Zone expected ON, detected ON → no penalty applied."""
        score = self._run("ON", "ON")
        assert score == pytest.approx(1.0)

    def test_illumination_penalty_configurable(self):
        """Custom penalty=0.5 → score halved, not zeroed."""
        score = self._run("OFF", "ON", penalty=0.5)
        # zone_score = 1.0, penalty=0.5 → 1.0 * (1 - 0.5) = 0.5
        assert score == pytest.approx(0.5)

    def test_illumination_no_penalty_when_state_matches(self):
        """Correct illumination state detected → score unaffected."""
        score = self._run("ON", "ON", penalty=0.9)
        assert score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Tests: text requirement evaluation
# ---------------------------------------------------------------------------

class TestTextRequirements:
    """Text requirement check via visual_features."""

    def test_text_requirement_pass(self):
        """Required text found in OCR features → compliant."""
        text_req = MagicMock()
        text_req.required_text = "EcoTank"
        text_req.match_type = "contains"
        text_req.case_sensitive = False
        text_req.confidence_threshold = 0.6
        text_req.mandatory = True

        prod_cfg = _make_shelf_product(
            "Epson_Top_Not_Backlit",
            text_requirements=[text_req],
        )
        shelf_cfg = _make_shelf_cfg("header", [prod_cfg])
        planogram_description = _make_planogram_description([shelf_cfg])

        identified = [
            _make_identified_product(
                "Epson_Top_Not_Backlit",
                "header",
                visual_features=["ocr: EcoTank Printer"],
            )
        ]

        gp = _make_type(shelves=[shelf_cfg])

        from unittest.mock import patch
        from parrot.models.compliance import TextComplianceResult

        found_result = TextComplianceResult(
            required_text="EcoTank",
            found=True,
            matched_features=["ocr: EcoTank Printer"],
            confidence=0.9,
            match_type="contains",
        )

        with patch(
            "parrot.pipelines.planogram.types.graphic_panel_display.TextMatcher.check_text_match",
            return_value=found_result,
        ):
            results = gp.check_planogram_compliance(identified, planogram_description)

        assert results[0].overall_text_compliant is True
        assert any(r.found for r in results[0].text_compliance_results)

    def test_text_requirement_fail(self):
        """Required text missing from OCR → non-compliant."""
        text_req = MagicMock()
        text_req.required_text = "EcoTank"
        text_req.match_type = "contains"
        text_req.case_sensitive = False
        text_req.confidence_threshold = 0.6
        text_req.mandatory = True

        prod_cfg = _make_shelf_product(
            "Epson_Top_Not_Backlit",
            text_requirements=[text_req],
        )
        shelf_cfg = _make_shelf_cfg("header", [prod_cfg])
        planogram_description = _make_planogram_description([shelf_cfg])

        identified = [
            _make_identified_product(
                "Epson_Top_Not_Backlit",
                "header",
                visual_features=["ocr: some other text"],
            )
        ]

        gp = _make_type(shelves=[shelf_cfg])

        from unittest.mock import patch
        from parrot.models.compliance import TextComplianceResult

        not_found_result = TextComplianceResult(
            required_text="EcoTank",
            found=False,
            matched_features=[],
            confidence=0.0,
            match_type="contains",
        )

        with patch(
            "parrot.pipelines.planogram.types.graphic_panel_display.TextMatcher.check_text_match",
            return_value=not_found_result,
        ):
            results = gp.check_planogram_compliance(identified, planogram_description)

        assert results[0].overall_text_compliant is False
        assert all(not r.found for r in results[0].text_compliance_results)


# ---------------------------------------------------------------------------
# Tests: no fact-tag / product counting
# ---------------------------------------------------------------------------

class TestNoFactTagLogic:
    """Verify no fact-tag attributes or product-counting logic in compliance output."""

    def test_no_fact_tag_logic(self):
        """ComplianceResult must not contain fact-tag related attributes."""
        prod_cfg = _make_shelf_product("Epson_Top_Not_Backlit")
        shelf_cfg = _make_shelf_cfg("header", [prod_cfg])
        planogram_description = _make_planogram_description([shelf_cfg])

        identified = [
            _make_identified_product("Epson_Top_Not_Backlit", "header", confidence=0.9)
        ]

        gp = _make_type(shelves=[shelf_cfg])
        results = gp.check_planogram_compliance(identified, planogram_description)

        assert len(results) == 1
        result = results[0]

        # No brand compliance (graphic panels don't check brand logo)
        assert result.brand_compliance_result is None

        # No unexpected products (graphic panels don't penalise extras)
        assert result.unexpected_products == []

        # Compliance result does not have any fact_tag attributes
        result_dict = result.model_dump()
        for key in result_dict:
            assert "fact" not in key.lower(), f"Unexpected fact-related key: {key}"


# ---------------------------------------------------------------------------
# Tests: type registration
# ---------------------------------------------------------------------------

class TestRegistration:
    """Verify GraphicPanelDisplay is registered in _PLANOGRAM_TYPES."""

    def test_type_registered(self):
        """'graphic_panel_display' key must exist in PlanogramCompliance._PLANOGRAM_TYPES."""
        assert "graphic_panel_display" in PlanogramCompliance._PLANOGRAM_TYPES

    def test_type_resolves_to_correct_class(self):
        """_PLANOGRAM_TYPES['graphic_panel_display'] must be GraphicPanelDisplay."""
        cls = PlanogramCompliance._PLANOGRAM_TYPES["graphic_panel_display"]
        assert cls is GraphicPanelDisplay

    def test_product_on_shelves_still_registered(self):
        """Existing 'product_on_shelves' registration must not be broken."""
        assert "product_on_shelves" in PlanogramCompliance._PLANOGRAM_TYPES
