"""Integration tests for WebScrapingTool PlanRegistry wiring."""
import pytest
from pathlib import Path

from parrot.tools.scraping.plan import ScrapingPlan
from parrot.tools.scraping.registry import PlanRegistry
from parrot.tools.scraping.plan_io import save_plan_to_disk, load_plan_from_disk


@pytest.fixture
def tmp_plans_dir(tmp_path):
    return tmp_path / "plans"


class TestFullPlanLifecycle:
    @pytest.mark.asyncio
    async def test_full_plan_lifecycle(self, tmp_plans_dir):
        """Create plan -> save -> register -> lookup -> load -> verify."""
        # Create
        plan = ScrapingPlan(
            url="https://example.com/products",
            objective="Extract products",
            steps=[{"action": "navigate", "url": "https://example.com/products"}],
        )

        # Save
        saved_path = await save_plan_to_disk(plan, tmp_plans_dir)
        assert saved_path.exists()

        # Register
        registry = PlanRegistry(plans_dir=tmp_plans_dir)
        relative = saved_path.relative_to(tmp_plans_dir)
        await registry.register(plan, str(relative))

        # Lookup
        entry = registry.lookup("https://example.com/products")
        assert entry is not None
        assert entry.domain == "example.com"

        # Load
        loaded = await load_plan_from_disk(tmp_plans_dir / entry.path)
        assert loaded.url == plan.url
        assert loaded.fingerprint == plan.fingerprint
        assert loaded.steps == plan.steps

    @pytest.mark.asyncio
    async def test_registry_persistence_across_instances(self, tmp_plans_dir):
        """Registry survives across new PlanRegistry instances."""
        plan = ScrapingPlan(
            url="https://test.com/page",
            objective="Test",
            steps=[{"action": "navigate", "url": "https://test.com/page"}],
        )
        saved_path = await save_plan_to_disk(plan, tmp_plans_dir)

        reg1 = PlanRegistry(plans_dir=tmp_plans_dir)
        await reg1.register(plan, str(saved_path.relative_to(tmp_plans_dir)))

        reg2 = PlanRegistry(plans_dir=tmp_plans_dir)
        await reg2.load()
        assert len(reg2.list_all()) == 1
        assert reg2.lookup("https://test.com/page") is not None

    @pytest.mark.asyncio
    async def test_cache_hit_updates_usage(self, tmp_plans_dir):
        """Looking up and touching a plan increments use_count."""
        plan = ScrapingPlan(
            url="https://shop.com/catalog",
            objective="Catalog",
            steps=[{"action": "navigate", "url": "https://shop.com/catalog"}],
        )
        saved_path = await save_plan_to_disk(plan, tmp_plans_dir)
        registry = PlanRegistry(plans_dir=tmp_plans_dir)
        await registry.register(plan, str(saved_path.relative_to(tmp_plans_dir)))

        # Simulate cache hit: lookup + touch
        entry = registry.lookup("https://shop.com/catalog")
        assert entry is not None
        assert entry.use_count == 0

        await registry.touch(plan.fingerprint)
        entry = registry.lookup("https://shop.com/catalog")
        assert entry.use_count == 1
        assert entry.last_used_at is not None

    @pytest.mark.asyncio
    async def test_tiered_lookup_path_prefix(self, tmp_plans_dir):
        """Path-prefix lookup finds parent plan for sub-path URL."""
        plan = ScrapingPlan(
            url="https://example.com/products",
            objective="Products",
            steps=[{"action": "navigate", "url": "https://example.com/products"}],
        )
        saved_path = await save_plan_to_disk(plan, tmp_plans_dir)
        registry = PlanRegistry(plans_dir=tmp_plans_dir)
        await registry.register(plan, str(saved_path.relative_to(tmp_plans_dir)))

        # Sub-path should match via tier 2
        entry = registry.lookup("https://example.com/products/electronics")
        assert entry is not None
        assert entry.domain == "example.com"

    @pytest.mark.asyncio
    async def test_multiple_domains_coexist(self, tmp_plans_dir):
        """Plans from different domains are stored and retrieved independently."""
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


class TestWebScrapingToolRegistry:
    def test_public_exports(self):
        """Verify ScrapingPlan and PlanRegistry are exported from __init__."""
        from parrot.tools.scraping import ScrapingPlan, PlanRegistry
        assert ScrapingPlan is not None
        assert PlanRegistry is not None

    def test_webscraping_tool_has_registry(self):
        """WebScrapingTool initializes with a PlanRegistry."""
        from parrot.tools.scraping.tool import WebScrapingTool
        tool = WebScrapingTool()
        assert hasattr(tool, '_plan_registry')
        assert isinstance(tool._plan_registry, PlanRegistry)

    def test_webscraping_tool_custom_plans_dir(self, tmp_plans_dir):
        """WebScrapingTool accepts a custom plans_dir."""
        from parrot.tools.scraping.tool import WebScrapingTool
        tool = WebScrapingTool(plans_dir=tmp_plans_dir)
        assert tool._plan_registry.plans_dir == tmp_plans_dir

    @pytest.mark.asyncio
    async def test_lookup_cached_plan_miss(self, tmp_plans_dir):
        """_lookup_cached_plan returns None on miss."""
        from parrot.tools.scraping.tool import WebScrapingTool
        tool = WebScrapingTool(plans_dir=tmp_plans_dir)
        result = await tool._lookup_cached_plan("https://unknown.com/page")
        assert result is None

    @pytest.mark.asyncio
    async def test_lookup_cached_plan_hit(self, tmp_plans_dir):
        """_lookup_cached_plan returns plan on hit."""
        from parrot.tools.scraping.tool import WebScrapingTool
        plan = ScrapingPlan(
            url="https://cached.com/data",
            objective="Get data",
            steps=[{"action": "navigate", "url": "https://cached.com/data"}],
        )
        saved_path = await save_plan_to_disk(plan, tmp_plans_dir)

        tool = WebScrapingTool(plans_dir=tmp_plans_dir)
        registry = tool._plan_registry
        await registry.load()
        await registry.register(plan, str(saved_path.relative_to(tmp_plans_dir)))

        result = await tool._lookup_cached_plan("https://cached.com/data")
        assert result is not None
        assert result.url == "https://cached.com/data"
        assert result.fingerprint == plan.fingerprint

    @pytest.mark.asyncio
    async def test_save_and_register_plan(self, tmp_plans_dir):
        """_save_and_register_plan persists and indexes a plan."""
        from parrot.tools.scraping.tool import WebScrapingTool
        tool = WebScrapingTool(plans_dir=tmp_plans_dir)
        plan = ScrapingPlan(
            url="https://new-site.com/page",
            objective="New scrape",
            steps=[{"action": "navigate", "url": "https://new-site.com/page"}],
        )
        await tool._save_and_register_plan(plan)

        # Verify it's now findable
        entry = tool._plan_registry.lookup("https://new-site.com/page")
        assert entry is not None
        assert entry.domain == "new-site.com"

        # Verify the file exists
        plan_path = tool._plan_registry.plans_dir / entry.path
        assert plan_path.exists()
