"""Tests for base_registry.py — BasePlanRegistry generic implementation."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parrot_tools.scraping.base_registry import BasePlanRegistry
from parrot_tools.scraping.plan import PlanRegistryEntry, ScrapingPlan, _compute_fingerprint, _normalize_url


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scraping_plan(url: str = "https://example.com/products", **kwargs) -> ScrapingPlan:
    """Build a minimal ScrapingPlan for testing."""
    defaults = {
        "url": url,
        "objective": "Test objective",
        "steps": [{"action": "navigate", "url": url}],
        "name": "test-plan",
    }
    defaults.update(kwargs)
    return ScrapingPlan(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBasePlanRegistryLoad:
    """Tests for BasePlanRegistry.load()."""

    @pytest.mark.asyncio
    async def test_load_empty_when_no_file(self, tmp_path: Path) -> None:
        """load() starts empty when the index file does not exist."""
        registry: BasePlanRegistry[ScrapingPlan] = BasePlanRegistry(plans_dir=tmp_path)
        await registry.load()
        assert registry.list_all() == []

    @pytest.mark.asyncio
    async def test_load_existing_index(self, tmp_path: Path) -> None:
        """load() reads an existing index and populates entries."""
        plan = _make_scraping_plan()
        entry = PlanRegistryEntry(
            name=plan.name or "test",
            plan_version=plan.version,
            url=plan.url,
            domain=plan.domain,
            fingerprint=plan.fingerprint,
            path="test-plan.json",
            created_at=datetime.now(timezone.utc),
        )
        index_data = {plan.fingerprint: entry.model_dump(mode="json")}
        (tmp_path / "registry.json").write_text(json.dumps(index_data, default=str))

        registry: BasePlanRegistry[ScrapingPlan] = BasePlanRegistry(plans_dir=tmp_path)
        await registry.load()
        assert len(registry.list_all()) == 1
        assert registry.list_all()[0].name == "test-plan"


class TestBasePlanRegistryLookup:
    """Tests for the 3-tier lookup in BasePlanRegistry."""

    @pytest.mark.asyncio
    async def test_tier1_exact_fingerprint(self, tmp_path: Path) -> None:
        """Tier 1: exact fingerprint match returns the entry."""
        plan = _make_scraping_plan("https://shop.example.com/products")
        registry: BasePlanRegistry[ScrapingPlan] = BasePlanRegistry(plans_dir=tmp_path)
        await registry.register(plan, "plan.json")

        result = registry.lookup("https://shop.example.com/products")
        assert result is not None
        assert result.fingerprint == plan.fingerprint

    @pytest.mark.asyncio
    async def test_tier2_path_prefix(self, tmp_path: Path) -> None:
        """Tier 2: a more-general path prefix matches a more-specific URL."""
        plan = _make_scraping_plan("https://shop.example.com/products")
        registry: BasePlanRegistry[ScrapingPlan] = BasePlanRegistry(plans_dir=tmp_path)
        await registry.register(plan, "plan.json")

        # A sub-path URL should match via prefix
        result = registry.lookup("https://shop.example.com/products/widget-123")
        assert result is not None
        assert result.fingerprint == plan.fingerprint

    @pytest.mark.asyncio
    async def test_tier3_domain_match(self, tmp_path: Path) -> None:
        """Tier 3: domain-only fallback returns a matching entry."""
        plan = _make_scraping_plan("https://shop.example.com/products")
        registry: BasePlanRegistry[ScrapingPlan] = BasePlanRegistry(plans_dir=tmp_path)
        await registry.register(plan, "plan.json")

        # Different path, same domain
        result = registry.lookup("https://shop.example.com/deals")
        assert result is not None
        assert result.domain == "shop.example.com"

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self, tmp_path: Path) -> None:
        """lookup() returns None when no entry matches the URL."""
        registry: BasePlanRegistry[ScrapingPlan] = BasePlanRegistry(plans_dir=tmp_path)
        await registry.load()
        assert registry.lookup("https://unknown.example.com/page") is None


class TestBasePlanRegistryRegister:
    """Tests for BasePlanRegistry.register()."""

    @pytest.mark.asyncio
    async def test_register_persists_to_disk(self, tmp_path: Path) -> None:
        """register() writes the index file to disk."""
        plan = _make_scraping_plan()
        registry: BasePlanRegistry[ScrapingPlan] = BasePlanRegistry(plans_dir=tmp_path)
        await registry.register(plan, "plan.json")

        index_file = tmp_path / "registry.json"
        assert index_file.exists()
        data = json.loads(index_file.read_text())
        assert plan.fingerprint in data

    @pytest.mark.asyncio
    async def test_register_multiple_plans(self, tmp_path: Path) -> None:
        """Registering multiple plans accumulates entries."""
        plan1 = _make_scraping_plan("https://a.example.com/")
        plan2 = _make_scraping_plan("https://b.example.com/")
        registry: BasePlanRegistry[ScrapingPlan] = BasePlanRegistry(plans_dir=tmp_path)
        await registry.register(plan1, "plan1.json")
        await registry.register(plan2, "plan2.json")
        assert len(registry.list_all()) == 2


class TestBasePlanRegistryInvalidate:
    """Tests for BasePlanRegistry.invalidate()."""

    @pytest.mark.asyncio
    async def test_invalidate_removes_entry(self, tmp_path: Path) -> None:
        """invalidate() removes the entry from the registry."""
        plan = _make_scraping_plan()
        registry: BasePlanRegistry[ScrapingPlan] = BasePlanRegistry(plans_dir=tmp_path)
        await registry.register(plan, "plan.json")
        assert len(registry.list_all()) == 1

        await registry.invalidate(plan.fingerprint)
        assert len(registry.list_all()) == 0

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_is_noop(self, tmp_path: Path) -> None:
        """invalidate() with unknown fingerprint logs warning and does nothing."""
        registry: BasePlanRegistry[ScrapingPlan] = BasePlanRegistry(plans_dir=tmp_path)
        await registry.load()
        # Should not raise
        await registry.invalidate("deadbeefdeadbeef")
        assert registry.list_all() == []


class TestBasePlanRegistryTouch:
    """Tests for BasePlanRegistry.touch()."""

    @pytest.mark.asyncio
    async def test_touch_increments_use_count(self, tmp_path: Path) -> None:
        """touch() increments use_count and sets last_used_at."""
        plan = _make_scraping_plan()
        registry: BasePlanRegistry[ScrapingPlan] = BasePlanRegistry(plans_dir=tmp_path)
        await registry.register(plan, "plan.json")

        await registry.touch(plan.fingerprint)
        entry = registry.lookup(plan.url)
        assert entry is not None
        assert entry.use_count == 1
        assert entry.last_used_at is not None


class TestBasePlanRegistryRemove:
    """Tests for BasePlanRegistry.remove()."""

    @pytest.mark.asyncio
    async def test_remove_by_name(self, tmp_path: Path) -> None:
        """remove() deletes entry by name and returns True."""
        plan = _make_scraping_plan()
        registry: BasePlanRegistry[ScrapingPlan] = BasePlanRegistry(plans_dir=tmp_path)
        await registry.register(plan, "plan.json")

        result = await registry.remove("test-plan")
        assert result is True
        assert registry.list_all() == []

    @pytest.mark.asyncio
    async def test_remove_nonexistent_returns_false(self, tmp_path: Path) -> None:
        """remove() returns False when the name is not found."""
        registry: BasePlanRegistry[ScrapingPlan] = BasePlanRegistry(plans_dir=tmp_path)
        await registry.load()
        result = await registry.remove("not-here")
        assert result is False


class TestPlanRegistryInheritance:
    """Verify PlanRegistry correctly inherits from BasePlanRegistry."""

    def test_plan_registry_is_base(self) -> None:
        """PlanRegistry is a subclass of BasePlanRegistry."""
        from parrot_tools.scraping.registry import PlanRegistry
        assert issubclass(PlanRegistry, BasePlanRegistry)

    @pytest.mark.asyncio
    async def test_plan_registry_register(self, tmp_path: Path) -> None:
        """PlanRegistry.register() uses ScrapingPlan.created_at."""
        from parrot_tools.scraping.registry import PlanRegistry
        plan = _make_scraping_plan()
        reg = PlanRegistry(plans_dir=tmp_path)
        await reg.register(plan, "plan.json")
        entry = reg.lookup(plan.url)
        assert entry is not None
        assert entry.name == "test-plan"
