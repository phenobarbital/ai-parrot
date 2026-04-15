"""Tests for pre-built ExtractionPlan JSON files."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot_tools.scraping.extraction_models import ExtractionPlan
from parrot_tools.scraping.extraction_registry import ExtractionPlanRegistry


# Locate the pre-built plans directory relative to this test file
PREBUILT_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "parrot_tools"
    / "scraping"
    / "extraction_plans"
    / "_prebuilt"
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPrebuiltPlanFiles:
    """Verify pre-built JSON plan files are valid ExtractionPlans."""

    def test_prebuilt_dir_exists(self) -> None:
        """The _prebuilt directory exists."""
        assert PREBUILT_DIR.exists(), f"Pre-built plans directory not found: {PREBUILT_DIR}"

    def test_generic_ecommerce_exists(self) -> None:
        """generic_ecommerce.json file exists."""
        assert (PREBUILT_DIR / "generic_ecommerce.json").exists()

    def test_generic_telecom_exists(self) -> None:
        """generic_telecom.json file exists."""
        assert (PREBUILT_DIR / "generic_telecom.json").exists()

    def test_generic_ecommerce_is_valid_extraction_plan(self) -> None:
        """generic_ecommerce.json parses as a valid ExtractionPlan."""
        raw = (PREBUILT_DIR / "generic_ecommerce.json").read_text()
        data = json.loads(raw)
        plan = ExtractionPlan.model_validate(data)
        assert plan.url is not None
        assert plan.objective is not None
        assert len(plan.entities) > 0
        assert plan.entities[0].entity_type == "product"

    def test_generic_telecom_is_valid_extraction_plan(self) -> None:
        """generic_telecom.json parses as a valid ExtractionPlan."""
        raw = (PREBUILT_DIR / "generic_telecom.json").read_text()
        data = json.loads(raw)
        plan = ExtractionPlan.model_validate(data)
        assert plan.url is not None
        assert plan.objective is not None
        assert len(plan.entities) > 0
        assert plan.entities[0].entity_type == "telecom_plan"

    def test_ecommerce_plan_has_required_fields(self) -> None:
        """generic_ecommerce.json has product_name and price fields."""
        raw = (PREBUILT_DIR / "generic_ecommerce.json").read_text()
        plan = ExtractionPlan.model_validate_json(raw)
        entity = plan.entities[0]
        field_names = {f.name for f in entity.fields}
        assert "product_name" in field_names
        assert "price" in field_names

    def test_telecom_plan_has_required_fields(self) -> None:
        """generic_telecom.json has plan_name and monthly_price fields."""
        raw = (PREBUILT_DIR / "generic_telecom.json").read_text()
        plan = ExtractionPlan.model_validate_json(raw)
        entity = plan.entities[0]
        field_names = {f.name for f in entity.fields}
        assert "plan_name" in field_names
        assert "monthly_price" in field_names

    def test_all_json_files_are_valid_plans(self) -> None:
        """All JSON files in _prebuilt/ parse as valid ExtractionPlans."""
        json_files = list(PREBUILT_DIR.glob("*.json"))
        assert len(json_files) >= 2, "Expected at least 2 pre-built plans"
        for json_file in json_files:
            raw = json_file.read_text()
            data = json.loads(raw)
            try:
                plan = ExtractionPlan.model_validate(data)
                assert plan.url, f"{json_file.name}: url must be non-empty"
                assert plan.objective, f"{json_file.name}: objective must be non-empty"
                assert len(plan.entities) > 0, f"{json_file.name}: must have at least one entity"
            except Exception as exc:
                pytest.fail(f"{json_file.name} is not a valid ExtractionPlan: {exc}")

    def test_plans_have_auto_populated_fingerprint(self) -> None:
        """ExtractionPlan auto-populates fingerprint from URL."""
        for json_file in PREBUILT_DIR.glob("*.json"):
            raw = json_file.read_text()
            data = json.loads(raw)
            plan = ExtractionPlan.model_validate(data)
            assert len(plan.fingerprint) == 16, (
                f"{json_file.name}: fingerprint should be 16 chars, got: {plan.fingerprint!r}"
            )

    def test_plans_auto_populate_domain(self) -> None:
        """ExtractionPlan auto-populates domain from URL."""
        for json_file in PREBUILT_DIR.glob("*.json"):
            raw = json_file.read_text()
            data = json.loads(raw)
            plan = ExtractionPlan.model_validate(data)
            assert plan.domain, f"{json_file.name}: domain should be auto-populated"


class TestPrebuiltPlanLoading:
    """Test loading pre-built plans via ExtractionPlanRegistry."""

    @pytest.mark.asyncio
    async def test_load_prebuilt_registers_all_plans(self, tmp_path: Path) -> None:
        """load_prebuilt() registers all plans from the _prebuilt directory."""
        reg = ExtractionPlanRegistry(plans_dir=tmp_path)
        count = await reg.load_prebuilt(PREBUILT_DIR)
        assert count >= 2

    @pytest.mark.asyncio
    async def test_load_prebuilt_sets_source_to_developer(self, tmp_path: Path) -> None:
        """load_prebuilt() sets source='developer' on all loaded plans."""
        reg = ExtractionPlanRegistry(plans_dir=tmp_path)
        await reg.load_prebuilt(PREBUILT_DIR)
        entries = reg.list_all()
        assert len(entries) >= 2
        for entry in entries:
            plan = await reg.load_plan(entry.fingerprint)
            assert plan is not None
            assert plan.source == "developer", (
                f"Expected source='developer', got '{plan.source}' for {entry.name}"
            )
