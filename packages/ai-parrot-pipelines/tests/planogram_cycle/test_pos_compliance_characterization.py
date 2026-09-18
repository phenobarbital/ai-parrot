"""Characterization tests: ProductOnShelves.check_planogram_compliance as it behaves TODAY (FEAT-574).

These tests pin legacy behaviour, quirks included. Do not "fix" an expectation
without reading spec §7 — the migrated scoring formula lives elsewhere.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from parrot.models.compliance import ComplianceResult, ComplianceStatus
from parrot.models.detections import DetectionBox, IdentifiedProduct
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.types import ProductOnShelves


def shelf(level: str, products: List[Dict[str, Any]], **extra: Any) -> Dict[str, Any]:
    """Raw shelf dict; ``extra`` carries compliance_threshold, allow_extra_products, *_weight…"""
    return {"level": level, "height_ratio": 0.3, "products": products, **extra}


def expected(name: str, product_type: str = "product", **extra: Any) -> Dict[str, Any]:
    """Raw expected-product dict; ``extra`` carries illumination_required / illumination_penalty / visual_features."""
    return {"name": name, "product_type": product_type, **extra}


def make_handler(shelves: List[Dict[str, Any]], **top_level: Any) -> ProductOnShelves:
    """Build a real ProductOnShelves over a MagicMock pipeline.

    Args:
        shelves: Raw ``planogram_config["shelves"]``.
        **top_level: Extra raw keys, e.g. ``advertisement_endcap={...}``, ``product_subtypes=[...]``.

    Returns:
        A handler whose config is a real ``PlanogramConfig``.
    """
    raw = {
        "brand": "TestBrand",
        "category": "TestCategory",
        "aisle": {"name": "Electronics > Test", "lighting_conditions": "normal"},
        "shelves": shelves,
        **top_level,
    }
    config = PlanogramConfig(
        config_name="characterization",
        planogram_type="product_on_shelves",
        planogram_config=raw,
        roi_detection_prompt="roi",
        object_identification_prompt="objects",
    )
    pipeline = MagicMock()
    pipeline.logger = logging.getLogger("test.pos.characterization")
    return ProductOnShelves(pipeline=pipeline, config=config)


def prod(model: Optional[str], shelf_location: str, product_type: str = "product", **extra: Any) -> IdentifiedProduct:
    """An identified product placed on ``shelf_location`` (extra: brand, visual_features, ocr_text)."""
    return IdentifiedProduct(
        product_type=product_type,
        product_model=model,
        confidence=0.9,
        shelf_location=shelf_location,
        detection_box=DetectionBox(x1=10, y1=10, x2=110, y2=110, confidence=0.9),
        **extra,
    )


def check(handler: ProductOnShelves, products: List[IdentifiedProduct]) -> Dict[str, ComplianceResult]:
    """Run the method under test and index the results by shelf level (order asserted separately)."""
    results = handler.check_planogram_compliance(products, handler.config.get_planogram_description())
    return {r.shelf_level: r for r in results}


# --------------------------------------------------------------------------- Part 2: scores and statuses


def test_one_result_per_shelf_in_config_order() -> None:
    """Returns exactly one ComplianceResult per configured shelf, in config order."""
    handler = make_handler(
        [
            shelf("top", [expected("ES-400")]),
            shelf("middle", [expected("RR-60")]),
            shelf("bottom", [expected("DS-770")]),
        ]
    )
    results = handler.check_planogram_compliance([], handler.config.get_planogram_description())
    assert [r.shelf_level for r in results] == ["top", "middle", "bottom"]
    assert all(isinstance(r, ComplianceResult) for r in results)


def test_pos_basic_score_and_status_characterization() -> None:
    """basic_score = matched/expected; COMPLIANT needs basic_score >= threshold; all-missing ⇒ MISSING."""
    handler = make_handler(
        [shelf("top", [expected("ES-400"), expected("RR-60")]), shelf("bottom", [expected("DS-770")])]
    )
    by = check(handler, [prod("ES-400", "top"), prod("RR-60", "top")])
    assert by["top"].compliance_status == ComplianceStatus.COMPLIANT
    assert by["top"].missing_products == []
    assert by["bottom"].compliance_status == ComplianceStatus.MISSING  # basic 0.0 and expected > 0
    assert by["bottom"].missing_products == ["DS-770"]
    assert by["bottom"].compliance_score == pytest.approx(0.3)  # 0.0·0.8 + 1.0·0.1 + 1.0·0.2


def test_pos_weights_sum_quirk_characterization() -> None:
    """Non-header default weights are 0.8/0.1/0.2 (sum 1.1) — masked by the clamp at :777."""
    handler = make_handler([shelf("top", [expected("ES-400"), expected("RR-60")])])
    full = check(handler, [prod("ES-400", "top"), prod("RR-60", "top")])["top"]
    half = check(handler, [prod("ES-400", "top")])["top"]
    assert full.compliance_score == pytest.approx(1.0)  # 1.1 clamped
    assert half.compliance_score == pytest.approx(0.7)  # 0.5·0.8 + 0.1 + 0.2 — NOT 0.636 (normalised)
    assert half.compliance_status == ComplianceStatus.NON_COMPLIANT


def test_pos_threshold_uses_basic_score_only_characterization() -> None:
    """3 of 4 matched: combined 0.9 >= 0.8 but basic 0.75 < 0.8 ⇒ NON_COMPLIANT."""
    names = ["ES-400", "RR-60", "DS-770", "WF-110"]
    handler = make_handler([shelf("top", [expected(n) for n in names], compliance_threshold=0.8)])
    res = check(handler, [prod(n, "top") for n in names[:3]])["top"]
    assert res.compliance_score == pytest.approx(0.9)
    assert res.compliance_status == ComplianceStatus.NON_COMPLIANT

    lenient = make_handler([shelf("top", [expected(n) for n in names], compliance_threshold=0.7)])
    res_lenient = check(lenient, [prod(n, "top") for n in names[:3]])["top"]
    assert res_lenient.compliance_score == pytest.approx(0.9)
    assert res_lenient.compliance_status == ComplianceStatus.COMPLIANT


def test_pos_explicit_shelf_weights_characterization() -> None:
    """shelf.product_weight / text_weight / visual_weight override the defaults."""
    handler = make_handler(
        [
            shelf(
                "top",
                [expected("ES-400"), expected("RR-60")],
                product_weight=0.5,
                text_weight=0.25,
                visual_weight=0.25,
            )
        ]
    )
    res = check(handler, [prod("ES-400", "top")])["top"]
    assert res.compliance_score == pytest.approx(0.5 * 0.5 + 1.0 * 0.25 + 1.0 * 0.25)  # 0.75


def test_pos_zone_only_shelf_characterization() -> None:
    """Zero expected products ⇒ basic 0.0, NON_COMPLIANT (neither COMPLIANT nor MISSING), score 0.3."""
    handler = make_handler([shelf("zone", []), shelf("top", [expected("ES-400")])])
    zone = check(handler, [prod("ES-400", "top")])["zone"]
    assert zone.compliance_status == ComplianceStatus.NON_COMPLIANT
    assert zone.compliance_score == pytest.approx(0.3)

    tags_only = make_handler(
        [
            shelf(
                "tags",
                [expected("Tag A", "fact_tag"), expected("Tag B", "price_tag"), expected("Slot C", "slot")],
            ),
            shelf("top", [expected("ES-400")]),
        ]
    )
    tags = check(tags_only, [prod("ES-400", "top")])["tags"]
    assert tags.expected_products == []
    assert tags.compliance_status == ComplianceStatus.NON_COMPLIANT
    assert tags.compliance_score == pytest.approx(0.3)


def test_pos_never_emits_misplaced_characterization() -> None:
    """A product expected on 'top' but found on 'bottom' yields MISSING/NON_COMPLIANT, never MISPLACED."""
    handler = make_handler([shelf("top", [expected("ES-400")]), shelf("bottom", [expected("DS-770")])])
    by = check(handler, [prod("ES-400", "bottom"), prod("DS-770", "bottom")])
    assert all(r.compliance_status != ComplianceStatus.MISPLACED for r in by.values())
    assert by["top"].compliance_status == ComplianceStatus.MISSING
    assert by["bottom"].compliance_status == ComplianceStatus.COMPLIANT
    assert not any("ES-400" in u for u in by["bottom"].unexpected_products)


# --------------------------------------------------------------------------- Part 3: illumination, text, matching


def test_pos_illumination_penalty_characterization() -> None:
    """Nested illumination_required; default penalty 0.5 multiplies the UNCLAMPED combined score."""
    handler = make_handler([shelf("top", [expected("ES-400", illumination_required="on")])])
    res = check(handler, [prod("ES-400", "top", visual_features=["illumination_status: OFF"])])["top"]
    assert res.compliance_score == pytest.approx(0.55)  # 1.1 · (1 - 0.5/1), clamp happens AFTER
    assert res.compliance_status == ComplianceStatus.NON_COMPLIANT  # mismatch blocks COMPLIANT (:731)
    assert any("backlight OFF (required: ON)" in m for m in res.missing_products)
    assert any(label.endswith("(LIGHT_OFF)") for label in res.found_products)

    # (a) explicit penalty 1.0 ⇒ score 0.0.
    full_penalty = make_handler(
        [shelf("top", [expected("ES-400", illumination_required="on", illumination_penalty=1.0)])]
    )
    res_a = check(full_penalty, [prod("ES-400", "top", visual_features=["illumination_status: OFF"])])["top"]
    assert res_a.compliance_score == pytest.approx(0.0)
    assert res_a.compliance_status == ComplianceStatus.NON_COMPLIANT

    # (b) detected ON matches the requirement ⇒ no penalty, COMPLIANT.
    res_b = check(handler, [prod("ES-400", "top", visual_features=["illumination_status: ON"])])["top"]
    assert res_b.compliance_score == pytest.approx(1.0)
    assert res_b.compliance_status == ComplianceStatus.COMPLIANT
    assert res_b.missing_products == []

    # (c) no illumination feature on the product ⇒ detected None ⇒ no penalty.
    res_c = check(handler, [prod("ES-400", "top")])["top"]
    assert res_c.compliance_score == pytest.approx(1.0)
    assert res_c.compliance_status == ComplianceStatus.COMPLIANT


HEADER_ENDCAP = {
    "enabled": True,
    "position": "header",
    "text_requirements": [
        {"required_text": "Hello Savings", "match_type": "contains", "mandatory": True},
        {"required_text": "Goodbye Cartridges", "match_type": "contains", "mandatory": False},
    ],
}


def _header_handler() -> ProductOnShelves:
    return make_handler(
        [shelf("header", [expected("TestBrand Backlit", "promotional_graphic")])],
        advertisement_endcap=HEADER_ENDCAP,
    )


def test_pos_header_text_requirements_characterization() -> None:
    """Header: text_score = Σconf(found)/len(all reqs); mandatory miss ⇒ overall_text_compliant False."""
    handler = _header_handler()
    promo = prod(
        "TestBrand Backlit",
        "header",
        "promotional_graphic",
        brand="TestBrand",
        visual_features=["ocr:Hello Savings"],
    )
    res = check(handler, [promo])["header"]
    assert res.text_compliance_score == pytest.approx(0.5)  # 1 of 2 found, 'contains' confidence is binary 1.0
    assert res.overall_text_compliant is True  # the missed requirement is optional
    assert res.compliance_score == pytest.approx(0.64 + 0.5 * 0.2 + 0.16)  # header weights 0.64/0.2/0.16
    assert res.compliance_status == ComplianceStatus.COMPLIANT

    # Mandatory text missing ⇒ overall_text_compliant False ⇒ NON_COMPLIANT.
    promo_optional_only = prod(
        "TestBrand Backlit",
        "header",
        "promotional_graphic",
        brand="TestBrand",
        visual_features=["ocr:Goodbye Cartridges"],
    )
    res_missing = check(handler, [promo_optional_only])["header"]
    assert res_missing.overall_text_compliant is False
    assert res_missing.text_compliance_score == pytest.approx(0.5)
    assert res_missing.compliance_status == ComplianceStatus.NON_COMPLIANT


def test_pos_header_no_promos_keeps_text_score_characterization() -> None:
    """No promo on the header: overall_text_compliant False, but text_compliance_score STAYS 1.0 (:686-697)."""
    handler = _header_handler()
    res = check(handler, [])["header"]
    assert res.overall_text_compliant is False
    assert res.text_compliance_score == pytest.approx(1.0)
    assert res.compliance_score == pytest.approx(0.0 * 0.64 + 1.0 * 0.2 + 1.0 * 0.16)  # 0.36
    assert all(t.found is False for t in res.text_compliance_results)
    assert res.compliance_status == ComplianceStatus.NON_COMPLIANT


def test_pos_header_brand_gate_characterization() -> None:
    """Header is NON_COMPLIANT when no identified product carries planogram.brand — brand never SCORES (weight 0.0)."""
    handler = make_handler(
        [
            shelf("header", [expected("TestBrand Backlit", "promotional_graphic")]),
            shelf("top", [expected("ES-400")]),
        ],
        advertisement_endcap=HEADER_ENDCAP,
    )
    with_brand = check(
        handler,
        [
            prod(
                "TestBrand Backlit",
                "header",
                "promotional_graphic",
                brand="TestBrand",
                visual_features=["ocr:Hello Savings"],
            ),
            prod("ES-400", "top"),
        ],
    )
    without_brand = check(
        handler,
        [
            prod(
                "TestBrand Backlit",
                "header",
                "promotional_graphic",
                brand=None,
                visual_features=["ocr:Hello Savings"],
            ),
            prod("ES-400", "top"),
        ],
    )
    assert with_brand["header"].compliance_status == ComplianceStatus.COMPLIANT
    assert without_brand["header"].compliance_status == ComplianceStatus.NON_COMPLIANT
    assert without_brand["header"].compliance_score == pytest.approx(with_brand["header"].compliance_score)
    assert without_brand["header"].brand_compliance_result.found is False
    assert without_brand["header"].brand_compliance_result is without_brand["top"].brand_compliance_result


def test_pos_matching_rules_characterization() -> None:
    """Type equivalence, empty-base wildcard, greedy 1:1 and skipped types."""
    # (a) expected "printer" is matched by a found "product" with the same model.
    handler_a = make_handler([shelf("top", [expected("ES-400", "printer")])])
    res_a = check(handler_a, [prod("ES-400", "top", "product")])["top"]
    assert res_a.missing_products == []
    assert res_a.compliance_status == ComplianceStatus.COMPLIANT

    # (b) a found product with no model (empty base) matches any expected item of an equivalent type.
    handler_b = make_handler([shelf("top", [expected("RR-60", "product")])])
    res_b = check(handler_b, [prod(None, "top", "product_box")])["top"]
    assert res_b.missing_products == []
    assert res_b.compliance_status == ComplianceStatus.COMPLIANT

    # (c) two expected "ES-400" need two found products (greedy 1:1).
    handler_c = make_handler([shelf("top", [expected("ES-400"), expected("ES-400")])])
    res_c = check(handler_c, [prod("ES-400", "top")])["top"]
    assert res_c.missing_products == ["ES-400"]
    assert res_c.compliance_score == pytest.approx(0.5 * 0.8 + 0.1 + 0.2)  # basic 0.5

    # (d) skipped found types neither match nor count as unexpected.
    handler_d = make_handler([shelf("top", [expected("ES-400")])])
    skipped = [prod("ES-400", "top", t) for t in ("fact_tag", "price_tag", "brand_logo", "gap", "shelf")]
    res_d = check(handler_d, skipped)["top"]
    assert res_d.missing_products == ["ES-400"]
    assert res_d.unexpected_products == []
    assert res_d.compliance_status == ComplianceStatus.MISSING


def test_pos_unexpected_products_characterization() -> None:
    """allow_extra_products, 'expected elsewhere' protection and the major_unexpected filter."""
    # (a) unknown product on a fully matched shelf ⇒ unexpected and NON_COMPLIANT.
    strict = make_handler([shelf("top", [expected("ES-400")])])
    res_a = check(strict, [prod("ES-400", "top"), prod("ZZ-999", "top")])["top"]
    assert any("ZZ-999" in u for u in res_a.unexpected_products)
    assert res_a.compliance_status == ComplianceStatus.NON_COMPLIANT

    # (b) allow_extra_products=True ⇒ nothing unexpected, COMPLIANT.
    lenient = make_handler([shelf("top", [expected("ES-400")], allow_extra_products=True)])
    res_b = check(lenient, [prod("ES-400", "top"), prod("ZZ-999", "top")])["top"]
    assert res_b.unexpected_products == []
    assert res_b.compliance_status == ComplianceStatus.COMPLIANT

    # (c) an "ink" label is listed but is not 'major' ⇒ shelf stays COMPLIANT.
    res_c = check(strict, [prod("ES-400", "top"), prod("Ink Bottle 502", "top")])["top"]
    assert any("ink" in u.lower() for u in res_c.unexpected_products)
    assert res_c.compliance_status == ComplianceStatus.COMPLIANT
