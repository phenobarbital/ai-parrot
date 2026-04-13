# TASK-632: Unit Tests for ProductOnShelves Illumination

**Feature**: product-on-shelves-illumination
**Spec**: `sdd/specs/product-on-shelves-illumination.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-628, TASK-630, TASK-631
**Assigned-to**: unassigned

---

## Context

Module 5 of FEAT-091. All implementation tasks (TASK-628–631) are complete.
This task creates the test file covering all 12 unit tests defined in the spec
(§4 Test Specification) plus one backwards-compatibility regression test.

Spec section: §4 Unit Tests, §4 Test Data/Fixtures.

---

## Scope

Create `packages/ai-parrot-pipelines/tests/test_product_on_shelves_illumination.py`
with all tests listed in the spec. Tests use `unittest.mock` to avoid real LLM
calls. Follow the mock/fixture patterns established in
`tests/test_endcap_no_shelves_promotional.py`.

**NOT in scope**: Integration tests (marked explicitly as out of scope for this
ticket). No changes to existing test files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/tests/test_product_on_shelves_illumination.py` | CREATE | 12 unit tests for FEAT-091 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Use these exact imports — all confirmed to resolve:
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType, _DEFAULT_ILLUMINATION_PENALTY
from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves
from parrot_pipelines.planogram.types.endcap_no_shelves_promotional import EndcapNoShelvesPromotional
from parrot.models.detections import IdentifiedProduct, PlanogramDescription
from parrot.models.compliance import ComplianceStatus
from PIL import Image
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
```

### Existing Test Patterns to Follow

```python
# From tests/test_endcap_no_shelves_promotional.py — copy fixture structure:
@pytest.fixture
def mock_pipeline():
    pipeline = MagicMock()
    pipeline._downscale_image = MagicMock(return_value=Image.new("RGB", (100, 100)))
    # roi_client as async context manager:
    mock_client = AsyncMock()
    mock_client.ask_to_image = AsyncMock(return_value=MagicMock(output="LIGHT_ON"))
    pipeline.roi_client.__aenter__ = AsyncMock(return_value=mock_client)
    pipeline.roi_client.__aexit__ = AsyncMock(return_value=None)
    return pipeline

# PlanogramDescriptionFactory for building test configs:
from parrot.models.detections import PlanogramDescriptionFactory
planogram_description = PlanogramDescriptionFactory.create_planogram_description(config_dict)

# ProductOnShelves constructor:
pos = ProductOnShelves(pipeline=mock_pipeline, config=mock_config)
# mock_config must have:
#   .get_planogram_description() → PlanogramDescription
#   .endcap_geometry.left_margin_ratio, .right_margin_ratio
#   .detection_grid (can be None)
```

### Scanner Config Fixture (from spec §4)

```python
@pytest.fixture
def scanner_config_with_illumination():
    return {
        "shelves": [
            {
                "level": "header",
                "is_background": True,
                "products": [{
                    "name": "Epson Scanners Header Graphic (backlit)",
                    "product_type": "promotional_graphic",
                    "visual_features": ["large backlit lightbox"],
                    "illumination_required": "on",
                    "illumination_penalty": 0.5,
                }],
                "height_ratio": 0.25,
                "y_start_ratio": 0.0,
            },
        ],
        "advertisement_endcap": {
            "enabled": True,
            "position": "header",
            "product_weight": 0.8,
            "text_weight": 0.2,
        }
    }
```

### Does NOT Exist

- ~~`ProductOnShelves._check_illumination()`~~ — does NOT exist on ProductOnShelves directly;
  inherited from base after TASK-628; test via `pos._check_illumination` (inherited)
- ~~`ShelfProduct.illumination_required`~~ — NOT a Pydantic attribute; will raise AttributeError
- ~~`PlanogramDescription.illumination_required`~~ — does not exist
- ~~`pos.check_planogram_compliance()` returning a dict~~— returns `List[ComplianceResult]`
  (verified at `product_on_shelves.py:348`)

---

## Test Specification

```python
"""Unit tests for ProductOnShelves illumination support — FEAT-091."""
import asyncio
import inspect
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from parrot_pipelines.planogram.types.abstract import (
    AbstractPlanogramType,
    _DEFAULT_ILLUMINATION_PENALTY,
)
from parrot_pipelines.planogram.types.product_on_shelves import ProductOnShelves
from parrot_pipelines.planogram.types.endcap_no_shelves_promotional import (
    EndcapNoShelvesPromotional,
)
from parrot.models.detections import IdentifiedProduct, PlanogramDescriptionFactory
from parrot.models.compliance import ComplianceStatus


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def small_image():
    return Image.new("RGB", (400, 300), color=(128, 128, 128))


@pytest.fixture
def mock_pipeline():
    pipeline = MagicMock()
    pipeline._downscale_image = MagicMock(return_value=Image.new("RGB", (100, 100)))
    mock_client = AsyncMock()
    mock_client.ask_to_image = AsyncMock(return_value=MagicMock(output="LIGHT_ON"))
    pipeline.roi_client.__aenter__ = AsyncMock(return_value=mock_client)
    pipeline.roi_client.__aexit__ = AsyncMock(return_value=None)
    return pipeline


@pytest.fixture
def scanner_config_with_illumination():
    """Config mimicking epson_scanner_backlit with illumination_required."""
    return {
        "shelves": [
            {
                "level": "header",
                "is_background": True,
                "products": [{
                    "name": "Epson Scanners Header Graphic (backlit)",
                    "product_type": "promotional_graphic",
                    "visual_features": ["large backlit lightbox"],
                    "illumination_required": "on",
                    "illumination_penalty": 0.5,
                }],
                "height_ratio": 0.25,
                "y_start_ratio": 0.0,
            },
        ],
        "advertisement_endcap": {
            "enabled": True,
            "position": "header",
            "product_weight": 0.8,
            "text_weight": 0.2,
        }
    }


@pytest.fixture
def scanner_config_no_illumination():
    """Same config but WITHOUT illumination_required — backwards-compat fixture."""
    return {
        "shelves": [
            {
                "level": "header",
                "is_background": True,
                "products": [{
                    "name": "Epson Scanners Header Graphic",
                    "product_type": "promotional_graphic",
                    "visual_features": ["large backlit lightbox"],
                }],
                "height_ratio": 0.25,
            },
        ],
        "advertisement_endcap": {
            "enabled": True,
            "position": "header",
            "product_weight": 0.8,
            "text_weight": 0.2,
        }
    }


def _make_pos(mock_pipeline, config_dict):
    """Build a ProductOnShelves instance with mocked config."""
    pd = PlanogramDescriptionFactory.create_planogram_description(config_dict)
    mock_config = MagicMock()
    mock_config.get_planogram_description.return_value = pd
    mock_config.endcap_geometry.left_margin_ratio = 0.0
    mock_config.endcap_geometry.right_margin_ratio = 0.0
    mock_config.detection_grid = None
    # Attach raw dict for planogram_config access
    pd.planogram_config = config_dict
    return ProductOnShelves(pipeline=mock_pipeline, config=mock_config)


def _make_identified_product(name, product_type="promotional_graphic",
                               shelf="header", visual_features=None):
    return IdentifiedProduct(
        product_model=name,
        product_type=product_type,
        shelf_location=shelf,
        confidence=0.9,
        brand="Epson",
        visual_features=visual_features or [],
    )


# ──────────────────────────────────────────────────────────────────────────────
# Module 1 — base class tests
# ──────────────────────────────────────────────────────────────────────────────

class TestAbstractHasCheckIllumination:
    def test_abstract_has_check_illumination(self):
        """AbstractPlanogramType exposes _check_illumination as async method."""
        assert hasattr(AbstractPlanogramType, "_check_illumination")
        assert inspect.iscoroutinefunction(AbstractPlanogramType._check_illumination)

    def test_default_illumination_penalty_constant(self):
        """_DEFAULT_ILLUMINATION_PENALTY is 1.0 in abstract."""
        assert _DEFAULT_ILLUMINATION_PENALTY == 1.0


# ──────────────────────────────────────────────────────────────────────────────
# Module 2 — endcap inheritance
# ──────────────────────────────────────────────────────────────────────────────

class TestEndcapInheritsCheckIllumination:
    def test_endcap_inherits_check_illumination(self):
        """EndcapNoShelvesPromotional._check_illumination resolves to base class."""
        # After TASK-629, EndcapNoShelvesPromotional must NOT define its own method.
        assert "_check_illumination" not in EndcapNoShelvesPromotional.__dict__
        assert hasattr(EndcapNoShelvesPromotional, "_check_illumination")


# ──────────────────────────────────────────────────────────────────────────────
# Module 3 — detect_objects enrichment
# ──────────────────────────────────────────────────────────────────────────────

class TestDetectObjectsIlluminationEnrichment:
    @pytest.mark.asyncio
    async def test_no_illumination_config_no_llm_call(
        self, mock_pipeline, scanner_config_no_illumination, small_image
    ):
        """illumination_required absent → no LLM call, visual_features unchanged."""
        pos = _make_pos(mock_pipeline, scanner_config_no_illumination)
        fake_product = _make_identified_product("Epson Scanners Header Graphic")

        with patch.object(pos, "_detect_legacy", new=AsyncMock(
            return_value=([fake_product], [])
        )):
            with patch.object(pos, "_check_illumination", new=AsyncMock()) as mock_illum:
                products, _ = await pos.detect_objects(small_image, roi=None, macro_objects=None)
                mock_illum.assert_not_called()
        assert products[0].visual_features == []

    @pytest.mark.asyncio
    async def test_illumination_enrichment_called_once(
        self, mock_pipeline, scanner_config_with_illumination, small_image
    ):
        """With illumination_required, _check_illumination called once and result prepended."""
        pos = _make_pos(mock_pipeline, scanner_config_with_illumination)
        fake_product = _make_identified_product(
            "Epson Scanners Header Graphic (backlit)",
            visual_features=["large backlit lightbox"],
        )

        with patch.object(pos, "_detect_legacy", new=AsyncMock(
            return_value=([fake_product], [])
        )):
            with patch.object(pos, "_check_illumination",
                               new=AsyncMock(return_value="illumination_status: ON")) as mock_illum:
                products, _ = await pos.detect_objects(small_image, roi=None, macro_objects=None)
                mock_illum.assert_called_once()

        assert products[0].visual_features[0] == "illumination_status: ON"

    @pytest.mark.asyncio
    async def test_illumination_enrichment_none_result_not_prepended(
        self, mock_pipeline, scanner_config_with_illumination, small_image
    ):
        """If _check_illumination returns None, visual_features NOT modified."""
        pos = _make_pos(mock_pipeline, scanner_config_with_illumination)
        fake_product = _make_identified_product(
            "Epson Scanners Header Graphic (backlit)",
            visual_features=["large backlit lightbox"],
        )

        with patch.object(pos, "_detect_legacy", new=AsyncMock(
            return_value=([fake_product], [])
        )):
            with patch.object(pos, "_check_illumination", new=AsyncMock(return_value=None)):
                products, _ = await pos.detect_objects(small_image, roi=None, macro_objects=None)

        assert "illumination_status: ON" not in products[0].visual_features
        assert "illumination_status: OFF" not in products[0].visual_features


# ──────────────────────────────────────────────────────────────────────────────
# Module 4 — compliance penalty
# ──────────────────────────────────────────────────────────────────────────────

class TestComplianceIlluminationPenalty:

    def _run_compliance(self, mock_pipeline, config_dict, visual_features):
        """Helper: build ProductOnShelves and run check_planogram_compliance."""
        pos = _make_pos(mock_pipeline, config_dict)
        pd = pos.config.get_planogram_description()
        product_name = config_dict["shelves"][0]["products"][0]["name"]
        identified = [_make_identified_product(
            product_name, visual_features=visual_features
        )]
        return pos.check_planogram_compliance(identified, pd)

    def test_illumination_match_no_penalty(
        self, mock_pipeline, scanner_config_with_illumination
    ):
        """Expected ON + detected ON → score unchanged (no penalty)."""
        results = self._run_compliance(
            mock_pipeline, scanner_config_with_illumination,
            visual_features=["illumination_status: ON", "large backlit lightbox"],
        )
        header = next(r for r in results if r.shelf_level == "header")
        # basic_score should be 1.0 with no penalty
        assert header.compliance_score >= 0.9

    def test_illumination_mismatch_default_penalty(
        self, mock_pipeline, scanner_config_with_illumination
    ):
        """Expected ON + detected OFF + illumination_penalty 0.5 → score * 0.5."""
        results_match = self._run_compliance(
            mock_pipeline, scanner_config_with_illumination,
            visual_features=["illumination_status: ON"],
        )
        results_mismatch = self._run_compliance(
            mock_pipeline, scanner_config_with_illumination,
            visual_features=["illumination_status: OFF"],
        )
        header_match = next(r for r in results_match if r.shelf_level == "header")
        header_mismatch = next(r for r in results_mismatch if r.shelf_level == "header")
        assert header_mismatch.compliance_score < header_match.compliance_score

    def test_illumination_mismatch_custom_penalty_100(
        self, mock_pipeline
    ):
        """Expected ON + detected OFF + illumination_penalty 1.0 → score contribution → 0."""
        config = {
            "shelves": [{
                "level": "header",
                "is_background": True,
                "products": [{
                    "name": "Header Graphic",
                    "product_type": "promotional_graphic",
                    "visual_features": [],
                    "illumination_required": "on",
                    "illumination_penalty": 1.0,
                }],
                "height_ratio": 0.25,
            }],
            "advertisement_endcap": {
                "enabled": True, "position": "header",
                "product_weight": 1.0, "text_weight": 0.0,
            }
        }
        pos = _make_pos(mock_pipeline, config)
        pd = pos.config.get_planogram_description()
        identified = [_make_identified_product(
            "Header Graphic", visual_features=["illumination_status: OFF"]
        )]
        results = pos.check_planogram_compliance(identified, pd)
        header = next(r for r in results if r.shelf_level == "header")
        # With 100% penalty on the only product, basic_score contribution → 0
        assert header.compliance_score <= 0.05

    def test_illumination_none_no_penalty(
        self, mock_pipeline, scanner_config_with_illumination
    ):
        """Detected state None (no illumination feature) → no penalty applied."""
        results = self._run_compliance(
            mock_pipeline, scanner_config_with_illumination,
            visual_features=["large backlit lightbox"],  # no illumination_status entry
        )
        results_on = self._run_compliance(
            mock_pipeline, scanner_config_with_illumination,
            visual_features=["illumination_status: ON", "large backlit lightbox"],
        )
        header = next(r for r in results if r.shelf_level == "header")
        header_on = next(r for r in results_on if r.shelf_level == "header")
        # Without illumination feature → no penalty → score same as ON match
        assert abs(header.compliance_score - header_on.compliance_score) < 0.05

    def test_found_names_reflects_actual_state(
        self, mock_pipeline, scanner_config_with_illumination
    ):
        """On mismatch, found_products contains '{name} (LIGHT_OFF)'."""
        pos = _make_pos(mock_pipeline, scanner_config_with_illumination)
        pd = pos.config.get_planogram_description()
        identified = [_make_identified_product(
            "Epson Scanners Header Graphic (backlit)",
            visual_features=["illumination_status: OFF"],
        )]
        results = pos.check_planogram_compliance(identified, pd)
        header = next(r for r in results if r.shelf_level == "header")
        assert any("LIGHT_OFF" in p for p in header.found_products)

    def test_missing_list_records_mismatch(
        self, mock_pipeline, scanner_config_with_illumination
    ):
        """missing_products includes '{name} — backlight OFF (required: ON)' on mismatch."""
        pos = _make_pos(mock_pipeline, scanner_config_with_illumination)
        pd = pos.config.get_planogram_description()
        identified = [_make_identified_product(
            "Epson Scanners Header Graphic (backlit)",
            visual_features=["illumination_status: OFF"],
        )]
        results = pos.check_planogram_compliance(identified, pd)
        header = next(r for r in results if r.shelf_level == "header")
        assert any("backlight" in m.lower() for m in header.missing_products)

    def test_backwards_compat_no_illumination_field(
        self, mock_pipeline, scanner_config_no_illumination
    ):
        """Configs without illumination_required produce identical scores pre/post feature."""
        pos = _make_pos(mock_pipeline, scanner_config_no_illumination)
        pd = pos.config.get_planogram_description()
        identified = [_make_identified_product(
            "Epson Scanners Header Graphic",
            visual_features=["large backlit lightbox"],
        )]
        results = pos.check_planogram_compliance(identified, pd)
        header = next(r for r in results if r.shelf_level == "header")
        # With no illumination config, a matched product → basic_score 1.0
        assert header.compliance_score >= 0.75
```

---

## Acceptance Criteria

- [ ] File `tests/test_product_on_shelves_illumination.py` created
- [ ] All 12 test functions present and passing
- [ ] No real LLM calls made (all mocked)
- [ ] `pytest packages/ai-parrot-pipelines/tests/test_product_on_shelves_illumination.py -v` — all pass
- [ ] `pytest packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py -v` — still passes (regression check)

---

## Agent Instructions

1. Verify TASK-628, TASK-630, TASK-631 are all in `tasks/completed/`.
2. Copy the test scaffold above verbatim as the starting point.
3. Run tests; fix any fixture/mock issues that arise from the actual class shape.
4. Do NOT modify implementation files — if a test fails, diagnose and fix the test.
5. Run both test files to confirm zero regression in endcap tests.
6. Move this file to `tasks/completed/` and update index → `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
