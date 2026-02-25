"""End-to-end integration tests for ScrapingPlan & PlanRegistry (FEAT-012).

Exercises the full plan lifecycle across all modules:
model creation -> file I/O -> registry indexing -> lookup -> reload.
"""
import pytest
from pathlib import Path

from parrot.tools.scraping.plan import ScrapingPlan, PlanRegistryEntry
from parrot.tools.scraping.registry import PlanRegistry
from parrot.tools.scraping.plan_io import save_plan_to_disk, load_plan_from_disk


@pytest.fixture
def tmp_plans_dir(tmp_path):
    return tmp_path / "plans"


class TestScrapingPlanIntegration:
    @pytest.mark.asyncio
    async def test_full_plan_lifecycle(self, tmp_plans_dir):
        """Create plan -> save -> register -> lookup -> load -> verify."""
        plan = ScrapingPlan(
            url="https://shop.example.com/catalog/electronics",
            objective="Extract electronics catalog",
            steps=[
                {"action": "navigate", "url": "https://shop.example.com/catalog/electronics"},
                {"action": "wait", "condition": ".product-grid", "condition_type": "selector"},
                {"action": "get_html", "selector": ".product-grid"},
            ],
            tags=["ecommerce", "electronics"],
        )

        # Save to disk
        saved_path = await save_plan_to_disk(plan, tmp_plans_dir)
        assert saved_path.exists()

        # Register
        registry = PlanRegistry(plans_dir=tmp_plans_dir)
        relative = saved_path.relative_to(tmp_plans_dir)
        await registry.register(plan, str(relative))

        # Lookup (exact)
        entry = registry.lookup("https://shop.example.com/catalog/electronics")
        assert entry is not None
        assert entry.domain == "shop.example.com"

        # Load from disk
        loaded = await load_plan_from_disk(tmp_plans_dir / entry.path)
        assert loaded.url == plan.url
        assert loaded.fingerprint == plan.fingerprint
        assert loaded.steps == plan.steps
        assert loaded.tags == plan.tags

    @pytest.mark.asyncio
    async def test_registry_persistence(self, tmp_plans_dir):
        """Save registry, create new instance, load, verify entries survive."""
        plan = ScrapingPlan(
            url="https://news.example.com/articles",
            objective="Scrape articles",
            steps=[{"action": "navigate", "url": "https://news.example.com/articles"}],
        )
        saved_path = await save_plan_to_disk(plan, tmp_plans_dir)

        # First registry instance
        reg1 = PlanRegistry(plans_dir=tmp_plans_dir)
        await reg1.register(plan, str(saved_path.relative_to(tmp_plans_dir)))
        assert len(reg1.list_all()) == 1

        # Second instance — load from disk
        reg2 = PlanRegistry(plans_dir=tmp_plans_dir)
        await reg2.load()
        assert len(reg2.list_all()) == 1
        entry = reg2.lookup("https://news.example.com/articles")
        assert entry is not None
        assert entry.name == plan.name

    @pytest.mark.asyncio
    async def test_multi_domain_plans(self, tmp_plans_dir):
        """Multiple plans across different domains coexist."""
        plans = [
            ScrapingPlan(
                url=f"https://site{i}.com/page",
                objective=f"Scrape site{i}",
                steps=[{"action": "navigate", "url": f"https://site{i}.com/page"}],
            )
            for i in range(3)
        ]

        registry = PlanRegistry(plans_dir=tmp_plans_dir)
        for plan in plans:
            path = await save_plan_to_disk(plan, tmp_plans_dir)
            await registry.register(plan, str(path.relative_to(tmp_plans_dir)))

        assert len(registry.list_all()) == 3
        for i in range(3):
            entry = registry.lookup(f"https://site{i}.com/page")
            assert entry is not None
            assert entry.domain == f"site{i}.com"

    @pytest.mark.asyncio
    async def test_versioned_plans_coexist(self, tmp_plans_dir):
        """Different versions of a plan for the same URL are saved as separate files."""
        plan_v1 = ScrapingPlan(
            url="https://example.com/data",
            objective="Extract data v1",
            steps=[{"action": "navigate", "url": "https://example.com/data"}],
            version="1.0",
        )
        plan_v2 = ScrapingPlan(
            url="https://example.com/data",
            objective="Extract data v2",
            steps=[
                {"action": "navigate", "url": "https://example.com/data"},
                {"action": "wait", "condition": ".loaded", "condition_type": "selector"},
            ],
            version="2.0",
        )

        path_v1 = await save_plan_to_disk(plan_v1, tmp_plans_dir)
        path_v2 = await save_plan_to_disk(plan_v2, tmp_plans_dir)

        # Different files (different version in filename)
        assert path_v1 != path_v2
        assert path_v1.exists()
        assert path_v2.exists()

        # Both load correctly
        loaded_v1 = await load_plan_from_disk(path_v1)
        loaded_v2 = await load_plan_from_disk(path_v2)
        assert loaded_v1.version == "1.0"
        assert loaded_v2.version == "2.0"
        assert len(loaded_v2.steps) == 2

    @pytest.mark.asyncio
    async def test_tiered_lookup_all_tiers(self, tmp_plans_dir):
        """Verify all three lookup tiers: exact -> path-prefix -> domain."""
        plan = ScrapingPlan(
            url="https://example.com/products",
            objective="Products",
            steps=[{"action": "navigate", "url": "https://example.com/products"}],
        )
        path = await save_plan_to_disk(plan, tmp_plans_dir)
        registry = PlanRegistry(plans_dir=tmp_plans_dir)
        await registry.register(plan, str(path.relative_to(tmp_plans_dir)))

        # Tier 1: exact fingerprint
        exact = registry.lookup("https://example.com/products")
        assert exact is not None

        # Tier 2: path-prefix
        prefix = registry.lookup("https://example.com/products/shoes/nike")
        assert prefix is not None

        # Tier 3: domain-only fallback
        domain = registry.lookup("https://example.com/completely-different")
        assert domain is not None

        # No match: different domain
        miss = registry.lookup("https://other-site.com/page")
        assert miss is None

    @pytest.mark.asyncio
    async def test_touch_and_usage_tracking(self, tmp_plans_dir):
        """Touch increments use_count and sets last_used_at through full lifecycle."""
        plan = ScrapingPlan(
            url="https://tracked.com/page",
            objective="Track usage",
            steps=[{"action": "navigate", "url": "https://tracked.com/page"}],
        )
        path = await save_plan_to_disk(plan, tmp_plans_dir)
        registry = PlanRegistry(plans_dir=tmp_plans_dir)
        await registry.register(plan, str(path.relative_to(tmp_plans_dir)))

        # Initial state
        entry = registry.lookup("https://tracked.com/page")
        assert entry.use_count == 0
        assert entry.last_used_at is None

        # Touch three times
        for _ in range(3):
            await registry.touch(plan.fingerprint)

        entry = registry.lookup("https://tracked.com/page")
        assert entry.use_count == 3
        assert entry.last_used_at is not None

        # Verify persistence
        reg2 = PlanRegistry(plans_dir=tmp_plans_dir)
        await reg2.load()
        entry2 = reg2.lookup("https://tracked.com/page")
        assert entry2.use_count == 3

    @pytest.mark.asyncio
    async def test_remove_then_lookup_returns_none(self, tmp_plans_dir):
        """After removing a plan, lookup returns None."""
        plan = ScrapingPlan(
            url="https://removable.com/page",
            objective="To be removed",
            steps=[{"action": "navigate", "url": "https://removable.com/page"}],
        )
        path = await save_plan_to_disk(plan, tmp_plans_dir)
        registry = PlanRegistry(plans_dir=tmp_plans_dir)
        await registry.register(plan, str(path.relative_to(tmp_plans_dir)))

        assert registry.lookup("https://removable.com/page") is not None
        removed = await registry.remove(plan.name)
        assert removed is True
        assert registry.lookup("https://removable.com/page") is None

    @pytest.mark.asyncio
    async def test_fingerprint_stability_in_lifecycle(self, tmp_plans_dir):
        """Plans created from URLs with query params match the same registry entry."""
        plan = ScrapingPlan(
            url="https://example.com/search",
            objective="Search",
            steps=[{"action": "navigate", "url": "https://example.com/search"}],
        )
        path = await save_plan_to_disk(plan, tmp_plans_dir)
        registry = PlanRegistry(plans_dir=tmp_plans_dir)
        await registry.register(plan, str(path.relative_to(tmp_plans_dir)))

        # Lookup with query params should still match (tier 1, same fingerprint)
        entry = registry.lookup("https://example.com/search?q=test&page=2")
        assert entry is not None
        assert entry.fingerprint == plan.fingerprint

    def test_public_exports(self):
        """Verify public exports from __init__.py."""
        from parrot.tools.scraping import ScrapingPlan, PlanRegistry
        assert ScrapingPlan is not None
        assert PlanRegistry is not None

    def test_public_exports_all_components(self):
        """Verify all expected exports are available."""
        from parrot.tools.scraping import (
            WebScrapingTool,
            WebScrapingToolArgs,
            ScrapingResult,
            ScrapingPlan,
            PlanRegistry,
        )
        assert WebScrapingTool is not None
        assert WebScrapingToolArgs is not None
        assert ScrapingResult is not None
        assert ScrapingPlan is not None
        assert PlanRegistry is not None
