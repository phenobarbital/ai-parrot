"""Unit tests for EndcapNoShelvesPromotional — FEAT-090."""
import asyncio
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType
from parrot_pipelines.planogram.types.endcap_no_shelves_promotional import (
    EndcapNoShelvesPromotional,
)
from parrot_pipelines.planogram.types.graphic_panel_display import GraphicPanelDisplay
from parrot.models.compliance import ComplianceStatus
from parrot.models.detections import IdentifiedProduct


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def three_zone_config():
    """Three-zone planogram config: header (backlit, mandatory), middle (mandatory),
    bottom (optional)."""
    return {
        "shelves": [
            {
                "level": "header",
                "products": [
                    {
                        "name": "Epson_Top_Backlit_ON",
                        "mandatory": True,
                        "product_type": "promotional_graphic",
                        "visual_features": ["illumination_status: ON"],
                        "text_requirements": [
                            {
                                "mandatory": True,
                                "match_type": "contains",
                                "required_text": "Hello Savings",
                            }
                        ],
                    }
                ],
            },
            {
                "level": "middle",
                "products": [
                    {
                        "name": "Epson_Comparison_Table",
                        "mandatory": True,
                        "product_type": "product",
                        "visual_features": ["comparison chart"],
                    }
                ],
            },
            {
                "level": "bottom",
                "products": [
                    {
                        "name": "Epson_Base_Special_Offer",
                        "mandatory": False,
                        "product_type": "product",
                        "visual_features": [],
                    }
                ],
            },
        ]
    }


def _make_pipeline() -> MagicMock:
    p = MagicMock()
    p.logger = MagicMock()
    return p


def _make_config(pcfg: dict) -> MagicMock:
    c = MagicMock()
    c.planogram_config = pcfg
    desc = MagicMock()
    desc.brand = "TestBrand"
    desc.global_compliance_threshold = 0.8
    c.get_planogram_description.return_value = desc
    return c


def _make_desc() -> MagicMock:
    d = MagicMock()
    d.global_compliance_threshold = 0.8
    return d


def _mkprod(
    name: str,
    shelf: str,
    features: List[str],
    conf: float = 0.5,
) -> IdentifiedProduct:
    return IdentifiedProduct(
        product_model=name,
        product_type="graphic_zone",
        confidence=conf,
        visual_features=features,
        shelf_location=shelf,
    )


def _mock_img() -> Image.Image:
    return Image.new("RGB", (100, 100))


# ---------------------------------------------------------------------------
# Module 1 — _extract_illumination_state in AbstractPlanogramType
# ---------------------------------------------------------------------------

def test_extract_illumination_state_in_base():
    """Helper is accessible from AbstractPlanogramType and returns 'on'."""
    result = AbstractPlanogramType._extract_illumination_state(
        ["illumination_status: ON", "ocr: Hello"]
    )
    assert result == "on"


def test_extract_illumination_state_off():
    """Helper returns 'off' for lowercase/uppercase OFF."""
    result = AbstractPlanogramType._extract_illumination_state(
        ["illumination_status: OFF"]
    )
    assert result == "off"


def test_extract_illumination_state_none():
    """Helper returns None when no illumination_status feature is present."""
    result = AbstractPlanogramType._extract_illumination_state(["ocr: Hello"])
    assert result is None


# ---------------------------------------------------------------------------
# Module 2+3 — detect_objects + check_planogram_compliance
# ---------------------------------------------------------------------------

def test_illumination_on_compliant(three_zone_config):
    """Zone found with backlight ON → COMPLIANT, score 1.0."""
    t = EndcapNoShelvesPromotional(_make_pipeline(), _make_config(three_zone_config))
    products = [
        _mkprod("Epson_Top_Backlit_ON", "header", ["illumination_status: on"]),
        _mkprod("Epson_Comparison_Table", "middle", []),
        _mkprod("Epson_Base_Special_Offer", "bottom", []),
    ]
    results = t.check_planogram_compliance(products, _make_desc())
    header = next(r for r in results if r.shelf_level == "header")
    assert header.compliance_status == ComplianceStatus.COMPLIANT
    assert header.compliance_score == 1.0


def test_illumination_off_noncompliant(three_zone_config):
    """Zone found with backlight OFF → NON_COMPLIANT, score 0.0."""
    t = EndcapNoShelvesPromotional(_make_pipeline(), _make_config(three_zone_config))
    products = [
        _mkprod("Epson_Top_Backlit_ON", "header", ["illumination_status: off"]),
        _mkprod("Epson_Comparison_Table", "middle", []),
    ]
    results = t.check_planogram_compliance(products, _make_desc())
    header = next(r for r in results if r.shelf_level == "header")
    assert header.compliance_status == ComplianceStatus.NON_COMPLIANT
    assert header.compliance_score == 0.0


def test_illumination_off_reason_in_missing(three_zone_config):
    """missing_products contains a human-readable reason when backlight is OFF."""
    t = EndcapNoShelvesPromotional(_make_pipeline(), _make_config(three_zone_config))
    products = [
        _mkprod("Epson_Top_Backlit_ON", "header", ["illumination_status: off"]),
    ]
    results = t.check_planogram_compliance(products, _make_desc())
    header = next(r for r in results if r.shelf_level == "header")
    assert any("backlight OFF" in m for m in header.missing_products)
    assert any("required: ON" in m for m in header.missing_products)


def test_zone_not_found_missing(three_zone_config):
    """Mandatory zone absent from products list → MISSING."""
    t = EndcapNoShelvesPromotional(_make_pipeline(), _make_config(three_zone_config))
    results = t.check_planogram_compliance([], _make_desc())
    mandatory = [r for r in results if r.shelf_level in ("header", "middle")]
    assert all(r.compliance_status == ComplianceStatus.MISSING for r in mandatory)


def test_no_illumination_config_skips_check():
    """Zones without illumination_status in visual_features skip _check_illumination."""
    cfg = {
        "shelves": [
            {
                "level": "poster",
                "products": [
                    {
                        "name": "Poster",
                        "product_type": "graphic_zone",
                        "visual_features": ["large graphic"],
                        "mandatory": True,
                    }
                ],
            }
        ]
    }
    t = EndcapNoShelvesPromotional(_make_pipeline(), _make_config(cfg))
    with patch.object(t, "_check_illumination", new=AsyncMock()) as mock_check:
        asyncio.run(t.detect_objects(_mock_img(), None, []))
    mock_check.assert_not_called()


def test_three_zone_config(three_zone_config):
    """Three configured zones produce three independent ComplianceResults."""
    t = EndcapNoShelvesPromotional(_make_pipeline(), _make_config(three_zone_config))
    products = [
        _mkprod("Epson_Top_Backlit_ON", "header", ["illumination_status: on"]),
        _mkprod("Epson_Comparison_Table", "middle", []),
        # bottom (optional) intentionally absent
    ]
    results = t.check_planogram_compliance(products, _make_desc())
    assert len(results) == 3
    assert {r.shelf_level for r in results} == {"header", "middle", "bottom"}


def test_mandatory_false_zone_missing_still_compliant(three_zone_config):
    """Optional (mandatory=False) zone absent → COMPLIANT for that zone."""
    t = EndcapNoShelvesPromotional(_make_pipeline(), _make_config(three_zone_config))
    products = [
        _mkprod("Epson_Top_Backlit_ON", "header", ["illumination_status: on"]),
        _mkprod("Epson_Comparison_Table", "middle", []),
        # bottom absent — mandatory=False
    ]
    results = t.check_planogram_compliance(products, _make_desc())
    bottom = next(r for r in results if r.shelf_level == "bottom")
    assert bottom.compliance_status == ComplianceStatus.COMPLIANT


def test_status_not_missing_when_found(three_zone_config):
    """Zone found but backlight wrong → NON_COMPLIANT, not MISSING.

    Regression: old code used MISSING for all score=0 cases.
    """
    t = EndcapNoShelvesPromotional(_make_pipeline(), _make_config(three_zone_config))
    products = [
        _mkprod("Epson_Top_Backlit_ON", "header", ["illumination_status: off"]),
    ]
    results = t.check_planogram_compliance(products, _make_desc())
    header = next(r for r in results if r.shelf_level == "header")
    assert header.compliance_status == ComplianceStatus.NON_COMPLIANT
    assert "Epson_Top_Backlit_ON" in header.found_products


# ---------------------------------------------------------------------------
# Regression: GraphicPanelDisplay still works after helper move (TASK-624)
# ---------------------------------------------------------------------------

def test_graphic_panel_display_inherits_extract_illumination():
    """GraphicPanelDisplay inherits _extract_illumination_state from AbstractPlanogramType
    after TASK-624 moved the method to the base class."""
    result = GraphicPanelDisplay._extract_illumination_state(["illumination_status: ON"])
    assert result == "on"
    # Method must be defined in the base class, not duplicated in GraphicPanelDisplay
    assert "_extract_illumination_state" not in GraphicPanelDisplay.__dict__
    assert "_extract_illumination_state" in AbstractPlanogramType.__dict__
