"""Tests for PlanRegistry — TASK-039."""
import asyncio

import pytest

from parrot.tools.scraping.plan import ScrapingPlan
from parrot.tools.scraping.registry import PlanRegistry


@pytest.fixture
def sample_plan():
    return ScrapingPlan(
        url="https://example.com/products",
        objective="Extract product listings",
        steps=[
            {"action": "navigate", "url": "https://example.com/products"},
            {"action": "wait", "condition": ".product-list", "condition_type": "selector"},
        ],
        tags=["ecommerce"],
    )


@pytest.fixture
def tmp_plans_dir(tmp_path):
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    return plans_dir


@pytest.fixture
def registry(tmp_plans_dir):
    return PlanRegistry(plans_dir=tmp_plans_dir)


class TestPlanRegistry:
    @pytest.mark.asyncio
    async def test_register_and_lookup(self, registry, sample_plan):
        """Register a plan then look it up by URL."""
        await registry.register(sample_plan, "example.com/plan_v1.0.json")
        entry = registry.lookup("https://example.com/products")
        assert entry is not None
        assert entry.domain == "example.com"

    @pytest.mark.asyncio
    async def test_lookup_exact_fingerprint(self, registry, sample_plan):
        """Tier 1: exact fingerprint match returns correct entry."""
        await registry.register(sample_plan, "example.com/plan.json")
        entry = registry.lookup("https://example.com/products")
        assert entry is not None
        assert entry.fingerprint == sample_plan.fingerprint

    @pytest.mark.asyncio
    async def test_lookup_path_prefix(self, registry, sample_plan):
        """Tier 2: sub-path URL matches parent plan."""
        await registry.register(sample_plan, "example.com/plan.json")
        entry = registry.lookup("https://example.com/products/shoes")
        assert entry is not None
        assert entry.domain == "example.com"

    @pytest.mark.asyncio
    async def test_lookup_domain_only(self, registry, sample_plan):
        """Tier 3: domain-only match as fallback."""
        await registry.register(sample_plan, "example.com/plan.json")
        entry = registry.lookup("https://example.com/about")
        assert entry is not None
        assert entry.domain == "example.com"

    @pytest.mark.asyncio
    async def test_lookup_no_match(self, registry):
        """Returns None when no plan matches."""
        entry = registry.lookup("https://unknown.com/page")
        assert entry is None

    @pytest.mark.asyncio
    async def test_touch_increments_count(self, registry, sample_plan):
        """touch() updates last_used_at and use_count."""
        await registry.register(sample_plan, "example.com/plan.json")
        entry_before = registry.lookup(sample_plan.url)
        assert entry_before.use_count == 0
        await registry.touch(sample_plan.fingerprint)
        entry_after = registry.lookup(sample_plan.url)
        assert entry_after.use_count == 1
        assert entry_after.last_used_at is not None

    @pytest.mark.asyncio
    async def test_remove_by_name(self, registry, sample_plan):
        """remove() deletes entry from index."""
        await registry.register(sample_plan, "example.com/plan.json")
        removed = await registry.remove(sample_plan.name)
        assert removed is True
        assert registry.lookup(sample_plan.url) is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self, registry):
        """remove() returns False for missing entry."""
        removed = await registry.remove("nonexistent")
        assert removed is False

    @pytest.mark.asyncio
    async def test_concurrent_register(self, registry):
        """Multiple async register() calls don't corrupt index."""
        plans = [
            ScrapingPlan(
                url=f"https://site{i}.com/page",
                objective=f"task {i}",
                steps=[{"action": "navigate", "url": f"https://site{i}.com/page"}],
            )
            for i in range(10)
        ]
        await asyncio.gather(*[
            registry.register(p, f"site{i}.com/plan.json")
            for i, p in enumerate(plans)
        ])
        assert len(registry.list_all()) == 10

    @pytest.mark.asyncio
    async def test_registry_persistence(self, tmp_plans_dir, sample_plan):
        """Save registry, new instance loads entries."""
        reg1 = PlanRegistry(plans_dir=tmp_plans_dir)
        await reg1.register(sample_plan, "example.com/plan.json")

        reg2 = PlanRegistry(plans_dir=tmp_plans_dir)
        await reg2.load()
        assert len(reg2.list_all()) == 1

    @pytest.mark.asyncio
    async def test_get_by_name(self, registry, sample_plan):
        """get_by_name() returns the correct entry."""
        await registry.register(sample_plan, "example.com/plan.json")
        entry = registry.get_by_name(sample_plan.name)
        assert entry is not None
        assert entry.domain == "example.com"

    @pytest.mark.asyncio
    async def test_get_by_name_not_found(self, registry):
        """get_by_name() returns None for missing name."""
        assert registry.get_by_name("nonexistent") is None

    @pytest.mark.asyncio
    async def test_list_all_empty(self, registry):
        """list_all() returns empty list on fresh registry."""
        assert registry.list_all() == []

    @pytest.mark.asyncio
    async def test_load_empty_registry(self, registry):
        """load() on nonexistent file yields empty registry."""
        await registry.load()
        assert registry.list_all() == []
