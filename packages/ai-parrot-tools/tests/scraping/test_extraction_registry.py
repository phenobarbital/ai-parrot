"""Tests for extraction_registry.py — ExtractionPlanRegistry."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot_tools.scraping.extraction_models import EntityFieldSpec, EntitySpec, ExtractionPlan
from parrot_tools.scraping.extraction_registry import ExtractionPlanRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plan(url: str = "https://example.com/products", **kwargs) -> ExtractionPlan:
    """Build a minimal ExtractionPlan for testing."""
    entity = EntitySpec(
        entity_type="product",
        description="A product",
        fields=[
            EntityFieldSpec(name="name", description="Product name", selector=".name"),
        ],
    )
    defaults = {
        "url": url,
        "objective": "Extract products",
        "entities": [entity],
    }
    defaults.update(kwargs)
    return ExtractionPlan(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExtractionPlanRegistryRegister:
    """Tests for register_extraction_plan()."""

    @pytest.mark.asyncio
    async def test_register_creates_json_file(self, tmp_path: Path) -> None:
        """register_extraction_plan() saves a JSON file to plans_dir."""
        plan = _make_plan()
        reg = ExtractionPlanRegistry(plans_dir=tmp_path)
        await reg.register_extraction_plan(plan)

        expected_file = tmp_path / f"{plan.fingerprint}.json"
        assert expected_file.exists()
        data = json.loads(expected_file.read_text())
        assert data["url"] == plan.url

    @pytest.mark.asyncio
    async def test_register_creates_index_entry(self, tmp_path: Path) -> None:
        """register_extraction_plan() creates an entry in the index."""
        plan = _make_plan()
        reg = ExtractionPlanRegistry(plans_dir=tmp_path)
        await reg.register_extraction_plan(plan)

        entry = reg.lookup(plan.url)
        assert entry is not None
        assert entry.fingerprint == plan.fingerprint


class TestExtractionPlanRegistryLoad:
    """Tests for load_plan() and lookup_plan()."""

    @pytest.mark.asyncio
    async def test_load_plan_returns_plan(self, tmp_path: Path) -> None:
        """load_plan() returns the registered plan by fingerprint."""
        plan = _make_plan()
        reg = ExtractionPlanRegistry(plans_dir=tmp_path)
        await reg.register_extraction_plan(plan)

        loaded = await reg.load_plan(plan.fingerprint)
        assert loaded is not None
        assert loaded.url == plan.url
        assert loaded.objective == plan.objective

    @pytest.mark.asyncio
    async def test_load_plan_missing_returns_none(self, tmp_path: Path) -> None:
        """load_plan() returns None for an unknown fingerprint."""
        reg = ExtractionPlanRegistry(plans_dir=tmp_path)
        await reg.load()
        result = await reg.load_plan("deadbeefdeadbeef")
        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_plan_by_url(self, tmp_path: Path) -> None:
        """lookup_plan() finds and loads a plan by URL."""
        plan = _make_plan()
        reg = ExtractionPlanRegistry(plans_dir=tmp_path)
        await reg.register_extraction_plan(plan)

        loaded = await reg.lookup_plan(plan.url)
        assert loaded is not None
        assert loaded.fingerprint == plan.fingerprint

    @pytest.mark.asyncio
    async def test_lookup_plan_no_match_returns_none(self, tmp_path: Path) -> None:
        """lookup_plan() returns None when no plan matches."""
        reg = ExtractionPlanRegistry(plans_dir=tmp_path)
        await reg.load()
        assert await reg.lookup_plan("https://unknown.example.com") is None


class TestExtractionPlanRegistryLifecycle:
    """Tests for record_success() and record_failure()."""

    @pytest.mark.asyncio
    async def test_record_success_resets_failure_count(self, tmp_path: Path) -> None:
        """record_success() resets failure count to 0 (persisted in entry)."""
        plan = _make_plan()
        reg = ExtractionPlanRegistry(plans_dir=tmp_path)
        await reg.register_extraction_plan(plan)

        # Accumulate 2 failures first
        await reg.record_failure(plan.fingerprint)
        await reg.record_failure(plan.fingerprint)
        entry = reg._entries.get(plan.fingerprint)
        assert entry is not None and entry.consecutive_failures == 2

        await reg.record_success(plan.fingerprint)
        entry = reg._entries.get(plan.fingerprint)
        assert entry is not None and entry.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_record_failure_invalidates_after_threshold(self, tmp_path: Path) -> None:
        """record_failure() invalidates the plan after FAILURE_THRESHOLD failures."""
        plan = _make_plan()
        reg = ExtractionPlanRegistry(plans_dir=tmp_path)
        await reg.register_extraction_plan(plan)
        assert len(reg.list_all()) == 1

        for _ in range(ExtractionPlanRegistry.FAILURE_THRESHOLD):
            await reg.record_failure(plan.fingerprint)

        # Plan should be removed from registry after threshold — entry is gone
        assert len(reg.list_all()) == 0
        assert plan.fingerprint not in reg._entries

    @pytest.mark.asyncio
    async def test_record_success_touches_entry(self, tmp_path: Path) -> None:
        """record_success() updates last_used_at."""
        plan = _make_plan()
        reg = ExtractionPlanRegistry(plans_dir=tmp_path)
        await reg.register_extraction_plan(plan)

        await reg.record_success(plan.fingerprint)
        entry = reg.lookup(plan.url)
        assert entry is not None
        assert entry.use_count == 1


class TestExtractionPlanRegistryPrebuilt:
    """Tests for load_prebuilt()."""

    @pytest.mark.asyncio
    async def test_load_prebuilt_from_directory(self, tmp_path: Path) -> None:
        """load_prebuilt() loads valid ExtractionPlan JSON files."""
        prebuilt_dir = tmp_path / "prebuilt"
        prebuilt_dir.mkdir()

        plan = _make_plan("https://telecom.example.com/plans")
        plan_data = plan.model_dump()
        (prebuilt_dir / "telecom_plan.json").write_text(json.dumps(plan_data, default=str))

        reg_dir = tmp_path / "registry"
        reg_dir.mkdir()
        reg = ExtractionPlanRegistry(plans_dir=reg_dir)
        count = await reg.load_prebuilt(prebuilt_dir)

        assert count == 1
        loaded = await reg.lookup_plan("https://telecom.example.com/plans")
        assert loaded is not None
        assert loaded.source == "developer"

    @pytest.mark.asyncio
    async def test_load_prebuilt_nonexistent_dir(self, tmp_path: Path) -> None:
        """load_prebuilt() returns 0 when directory does not exist."""
        reg = ExtractionPlanRegistry(plans_dir=tmp_path)
        count = await reg.load_prebuilt(tmp_path / "nonexistent")
        assert count == 0

    @pytest.mark.asyncio
    async def test_load_prebuilt_skips_invalid_files(self, tmp_path: Path) -> None:
        """load_prebuilt() skips malformed JSON files."""
        prebuilt_dir = tmp_path / "prebuilt"
        prebuilt_dir.mkdir()
        (prebuilt_dir / "bad.json").write_text("not valid json")

        reg = ExtractionPlanRegistry(plans_dir=tmp_path / "registry")
        count = await reg.load_prebuilt(prebuilt_dir)
        assert count == 0
