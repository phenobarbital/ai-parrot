"""Integration tests for WebScrapingToolkit — TASK-055.

End-to-end tests exercising the full toolkit lifecycle using mocked
drivers and LLM clients.  No real browser is launched.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from parrot.tools.scraping.plan import ScrapingPlan
from parrot.tools.scraping.toolkit import WebScrapingToolkit
from parrot.tools.scraping.toolkit_models import PlanSummary


# ═══════════════════════════════════════════════════════════════════════
# Shared test data
# ═══════════════════════════════════════════════════════════════════════

SAMPLE_URL = "https://shop.example.com/products"
SAMPLE_OBJECTIVE = "Extract product names and prices"

SAMPLE_PLAN_DICT = {
    "url": SAMPLE_URL,
    "objective": SAMPLE_OBJECTIVE,
    "steps": [
        {"action": "navigate", "url": SAMPLE_URL},
        {"action": "wait", "condition": ".product-list", "condition_type": "selector"},
    ],
    "selectors": [
        {"name": "titles", "selector": "h2.title", "selector_type": "css",
         "extract_type": "text", "multiple": True},
    ],
}

HTML_BODY = (
    "<html><body>"
    "<div class='product-list'>"
    "<h2 class='title'>Widget A</h2>"
    "<h2 class='title'>Widget B</h2>"
    "</div>"
    "</body></html>"
)

SECOND_URL = "https://news.example.com/articles"
SECOND_PLAN_DICT = {
    "url": SECOND_URL,
    "objective": "Extract headlines",
    "steps": [
        {"action": "navigate", "url": SECOND_URL},
    ],
}


# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_llm_client():
    """LLM client that returns a valid plan JSON."""
    client = AsyncMock()
    client.complete = AsyncMock(return_value=json.dumps(SAMPLE_PLAN_DICT))
    return client


def _make_driver_mock():
    """Build a mock Selenium-like driver."""
    drv = MagicMock()
    type(drv).current_url = PropertyMock(return_value=SAMPLE_URL)
    type(drv).page_source = PropertyMock(return_value=HTML_BODY)
    drv.get = MagicMock()
    drv.quit = MagicMock()
    return drv


@pytest.fixture
def toolkit(tmp_path, mock_llm_client):
    """Fresh-mode toolkit with mock LLM and temp plans dir."""
    return WebScrapingToolkit(
        headless=True,
        plans_dir=tmp_path / "plans",
        llm_client=mock_llm_client,
    )


@pytest.fixture
def sample_plan():
    return ScrapingPlan(**SAMPLE_PLAN_DICT)


# ═══════════════════════════════════════════════════════════════════════
# Test classes
# ═══════════════════════════════════════════════════════════════════════

class TestPlanLifecycle:
    """Create → save → load round-trip via the toolkit."""

    @pytest.mark.asyncio
    async def test_full_plan_lifecycle(self, toolkit, sample_plan):
        """plan_create → plan_save → plan_load round-trip."""
        # Save
        result = await toolkit.plan_save(sample_plan)
        assert result.success is True
        assert result.registered is True

        # Load by URL
        loaded = await toolkit.plan_load(sample_plan.url)
        assert loaded is not None
        assert loaded.url == sample_plan.url
        assert loaded.objective == sample_plan.objective
        assert len(loaded.steps) == len(sample_plan.steps)

    @pytest.mark.asyncio
    async def test_plan_save_duplicate_blocked(self, toolkit, sample_plan):
        """Saving the same plan twice without overwrite returns failure."""
        await toolkit.plan_save(sample_plan)
        dup = await toolkit.plan_save(sample_plan)
        assert dup.success is False
        assert "already exists" in dup.message.lower()

    @pytest.mark.asyncio
    async def test_plan_save_overwrite(self, toolkit, sample_plan):
        """overwrite=True replaces existing plan."""
        await toolkit.plan_save(sample_plan)
        result = await toolkit.plan_save(sample_plan, overwrite=True)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_plan_load_not_found(self, toolkit):
        """plan_load returns None for unknown URL."""
        loaded = await toolkit.plan_load("https://nowhere.example.com/nope")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_plan_load_by_name(self, toolkit, sample_plan):
        """plan_load falls back to name-based lookup."""
        await toolkit.plan_save(sample_plan)
        loaded = await toolkit.plan_load(sample_plan.name)
        assert loaded is not None
        assert loaded.url == sample_plan.url

    @pytest.mark.asyncio
    async def test_plan_delete(self, toolkit, sample_plan):
        """plan_delete removes from registry and disk."""
        await toolkit.plan_save(sample_plan)
        deleted = await toolkit.plan_delete(sample_plan.name)
        assert deleted is True

        # Confirm gone
        loaded = await toolkit.plan_load(sample_plan.url)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_plan_delete_nonexistent(self, toolkit):
        """plan_delete returns False for missing plan."""
        assert await toolkit.plan_delete("no-such-plan") is False


class TestPlanList:
    """plan_list with filtering."""

    @pytest.mark.asyncio
    async def test_plan_list_returns_all(self, toolkit):
        """List all registered plans."""
        plan_a = ScrapingPlan(**SAMPLE_PLAN_DICT)
        plan_b = ScrapingPlan(**SECOND_PLAN_DICT)
        await toolkit.plan_save(plan_a)
        await toolkit.plan_save(plan_b)

        summaries = await toolkit.plan_list()
        assert len(summaries) == 2
        assert all(isinstance(s, PlanSummary) for s in summaries)

    @pytest.mark.asyncio
    async def test_plan_list_domain_filter(self, toolkit):
        """plan_list with domain_filter returns only matching plans."""
        plan_a = ScrapingPlan(**SAMPLE_PLAN_DICT)
        plan_b = ScrapingPlan(**SECOND_PLAN_DICT)
        await toolkit.plan_save(plan_a)
        await toolkit.plan_save(plan_b)

        filtered = await toolkit.plan_list(domain_filter="shop.example.com")
        assert len(filtered) == 1
        assert filtered[0].domain == "shop.example.com"

    @pytest.mark.asyncio
    async def test_plan_list_tag_filter(self, toolkit):
        """plan_list with tag_filter returns matching plans."""
        plan_tagged = ScrapingPlan(
            url=SAMPLE_URL,
            objective=SAMPLE_OBJECTIVE,
            steps=SAMPLE_PLAN_DICT["steps"],
            tags=["ecommerce"],
        )
        plan_untagged = ScrapingPlan(**SECOND_PLAN_DICT)
        await toolkit.plan_save(plan_tagged)
        await toolkit.plan_save(plan_untagged)

        filtered = await toolkit.plan_list(tag_filter="ecommerce")
        assert len(filtered) == 1
        assert "ecommerce" in filtered[0].tags

    @pytest.mark.asyncio
    async def test_plan_list_empty(self, toolkit):
        """Empty registry returns empty list."""
        summaries = await toolkit.plan_list()
        assert summaries == []


class TestScrapeWithCache:
    """Verify plan resolution chain: explicit → cache → auto-generate."""

    @pytest.mark.asyncio
    async def test_scrape_with_explicit_plan(self, toolkit, sample_plan):
        """Explicit plan argument bypasses cache and LLM."""
        drv = _make_driver_mock()
        with patch("parrot.tools.scraping.toolkit.driver_context") as ctx:
            ctx.return_value.__aenter__ = AsyncMock(return_value=drv)
            ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await toolkit.scrape(SAMPLE_URL, plan=sample_plan)

        assert result.success is True
        # LLM should not have been called
        toolkit._llm_client.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_scrape_uses_cache_hit(self, toolkit, sample_plan):
        """After plan_save, scrape resolves from cache without LLM call."""
        await toolkit.plan_save(sample_plan)

        drv = _make_driver_mock()
        with patch("parrot.tools.scraping.toolkit.driver_context") as ctx:
            ctx.return_value.__aenter__ = AsyncMock(return_value=drv)
            ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await toolkit.scrape(SAMPLE_URL)

        assert result.success is True
        toolkit._llm_client.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_scrape_auto_generate(self, toolkit):
        """No cache + objective triggers LLM auto-generation."""
        drv = _make_driver_mock()
        with patch("parrot.tools.scraping.toolkit.driver_context") as ctx:
            ctx.return_value.__aenter__ = AsyncMock(return_value=drv)
            ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await toolkit.scrape(
                SAMPLE_URL, objective="Get product info"
            )

        assert result.success is True
        # LLM was called to generate a plan
        toolkit._llm_client.complete.assert_called()

    @pytest.mark.asyncio
    async def test_scrape_no_plan_no_objective_raises(self, toolkit):
        """No plan, no cache, no objective → ValueError."""
        with pytest.raises(ValueError, match="No plan available"):
            await toolkit.scrape(SAMPLE_URL)

    @pytest.mark.asyncio
    async def test_scrape_raw_steps_bypasses_plan(self, toolkit):
        """Raw steps list bypasses plan resolution entirely."""
        drv = _make_driver_mock()
        with patch("parrot.tools.scraping.toolkit.driver_context") as ctx:
            ctx.return_value.__aenter__ = AsyncMock(return_value=drv)
            ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await toolkit.scrape(
                SAMPLE_URL,
                steps=[{"action": "navigate", "url": SAMPLE_URL}],
            )

        assert result.success is True
        toolkit._llm_client.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_scrape_with_save_plan(self, toolkit):
        """save_plan=True auto-saves the generated plan after scraping."""
        drv = _make_driver_mock()
        with patch("parrot.tools.scraping.toolkit.driver_context") as ctx:
            ctx.return_value.__aenter__ = AsyncMock(return_value=drv)
            ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            await toolkit.scrape(
                SAMPLE_URL, objective="Get products", save_plan=True
            )

        # Plan should now be in registry
        loaded = await toolkit.plan_load(SAMPLE_URL)
        assert loaded is not None
        assert loaded.url == SAMPLE_URL


class TestDriverModes:
    """Session-based vs fresh driver lifecycle."""

    @pytest.mark.asyncio
    async def test_session_mode_reuses_driver(self, tmp_path, mock_llm_client):
        """session_based=True reuses the same driver instance."""
        tk = WebScrapingToolkit(
            session_based=True,
            plans_dir=tmp_path / "plans",
            llm_client=mock_llm_client,
        )

        drv = _make_driver_mock()
        mock_setup = MagicMock()
        mock_setup.get_driver = AsyncMock(return_value=drv)

        plan = ScrapingPlan(**SAMPLE_PLAN_DICT)

        # Patch DriverRegistry.get at the toolkit's import location
        with patch(
            "parrot.tools.scraping.toolkit.DriverRegistry"
        ) as reg_cls:
            reg_cls.get = MagicMock(return_value=lambda cfg: mock_setup)
            await tk.start()

        # Session driver should be set
        assert tk._session_driver is drv
        mock_setup.get_driver.assert_called_once()

        # Now scrape — should use session driver, not create a new one
        with patch("parrot.tools.scraping.toolkit.driver_context") as ctx:
            ctx.return_value.__aenter__ = AsyncMock(return_value=drv)
            ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tk.scrape(SAMPLE_URL, plan=plan)

        assert result.success is True
        # driver_context was called with session_driver
        ctx.assert_called_once()
        call_kwargs = ctx.call_args
        assert call_kwargs[1].get("session_driver") is drv or (
            len(call_kwargs[0]) > 1 and call_kwargs[0][1] is drv
        )

        # Stop — patch _quit_driver to avoid calling quit on our mock in a way that breaks
        with patch("parrot.tools.scraping.toolkit._quit_driver", new_callable=AsyncMock):
            await tk.stop()
        assert tk._session_driver is None

    @pytest.mark.asyncio
    async def test_fresh_mode_creates_driver_each_time(self, toolkit, sample_plan):
        """Fresh mode (default) creates a new driver per scrape call."""
        drv1 = _make_driver_mock()
        drv2 = _make_driver_mock()
        call_count = 0

        async def fake_aenter(self_ctx):
            nonlocal call_count
            call_count += 1
            return drv1 if call_count == 1 else drv2

        with patch("parrot.tools.scraping.toolkit.driver_context") as ctx:
            ctx.return_value.__aenter__ = fake_aenter
            ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            await toolkit.scrape(SAMPLE_URL, plan=sample_plan)
            await toolkit.scrape(SAMPLE_URL, plan=sample_plan)

        # driver_context should have been called twice (once per scrape)
        assert ctx.call_count == 2

    @pytest.mark.asyncio
    async def test_fresh_mode_session_driver_is_none(self, toolkit):
        """Default toolkit has no session driver."""
        assert toolkit._session_driver is None
        assert toolkit._session_based is False


class TestToolSchemas:
    """get_tools() returns correct tool count and schemas."""

    def test_get_tools_returns_seven(self, toolkit):
        """get_tools() returns exactly 7 tools."""
        tools = toolkit.get_tools()
        assert len(tools) == 7

    def test_get_tools_tool_names(self, toolkit):
        """Tools have the expected names."""
        tools = toolkit.get_tools()
        names = {t.name for t in tools}
        expected = {
            "plan_create", "plan_save", "plan_load",
            "plan_list", "plan_delete", "scrape", "crawl",
        }
        assert names == expected

    def test_get_tools_have_descriptions(self, toolkit):
        """Every tool has a non-empty description."""
        tools = toolkit.get_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"

    def test_get_tools_have_schemas(self, toolkit):
        """Every tool has an args_schema (Pydantic model class)."""
        tools = toolkit.get_tools()
        for tool in tools:
            assert tool.args_schema is not None, f"Tool {tool.name} has no args_schema"


class TestPlanCreate:
    """plan_create with cache and force_regenerate."""

    @pytest.mark.asyncio
    async def test_plan_create_generates_via_llm(self, toolkit):
        """plan_create calls LLM when no cached plan exists."""
        plan = await toolkit.plan_create(SAMPLE_URL, SAMPLE_OBJECTIVE)
        assert isinstance(plan, ScrapingPlan)
        assert plan.url == SAMPLE_URL
        toolkit._llm_client.complete.assert_called()

    @pytest.mark.asyncio
    async def test_plan_create_returns_cached(self, toolkit, sample_plan):
        """plan_create returns cached plan when one exists."""
        await toolkit.plan_save(sample_plan)

        # Reset LLM mock call count
        toolkit._llm_client.complete.reset_mock()

        plan = await toolkit.plan_create(SAMPLE_URL, SAMPLE_OBJECTIVE)
        assert plan.url == SAMPLE_URL
        toolkit._llm_client.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_plan_create_force_regenerate(self, toolkit, sample_plan):
        """force_regenerate=True bypasses cache."""
        await toolkit.plan_save(sample_plan)
        toolkit._llm_client.complete.reset_mock()

        plan = await toolkit.plan_create(
            SAMPLE_URL, SAMPLE_OBJECTIVE, force_regenerate=True,
        )
        assert isinstance(plan, ScrapingPlan)
        toolkit._llm_client.complete.assert_called()


class TestCrawlDelegation:
    """crawl() delegates to CrawlEngine."""

    @pytest.mark.asyncio
    async def test_crawl_not_implemented_when_engine_missing(self, toolkit, sample_plan):
        """crawl() raises NotImplementedError when CrawlEngine is not available."""
        with pytest.raises(NotImplementedError, match="CrawlEngine is not available"):
            await toolkit.crawl(SAMPLE_URL, depth=2, plan=sample_plan)

    @pytest.mark.asyncio
    async def test_crawl_delegates_when_engine_available(self, toolkit, sample_plan):
        """crawl() delegates to CrawlEngine when importable."""
        import sys
        import types

        mock_engine_instance = MagicMock()
        mock_engine_instance.run = AsyncMock(return_value=MagicMock(pages=[]))

        # Create a fake crawl_engine module so the dynamic import succeeds
        fake_module = types.ModuleType("parrot.tools.scraping.crawl_engine")
        fake_module.CrawlEngine = MagicMock(return_value=mock_engine_instance)

        with patch.dict(sys.modules, {"parrot.tools.scraping.crawl_engine": fake_module}):
            await toolkit.crawl(SAMPLE_URL, depth=2, plan=sample_plan)

        mock_engine_instance.run.assert_called_once()


class TestConfigOverride:
    """Browser config override per scrape call."""

    @pytest.mark.asyncio
    async def test_scrape_with_config_override(self, toolkit, sample_plan):
        """browser_config_override applies without mutating toolkit config."""
        original_timeout = toolkit._config.default_timeout
        drv = _make_driver_mock()

        with patch("parrot.tools.scraping.toolkit.driver_context") as ctx:
            ctx.return_value.__aenter__ = AsyncMock(return_value=drv)
            ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            await toolkit.scrape(
                SAMPLE_URL,
                plan=sample_plan,
                browser_config_override={"default_timeout": 30},
            )

        # Original config unchanged
        assert toolkit._config.default_timeout == original_timeout

        # driver_context was called with a merged config
        call_args = ctx.call_args
        merged_config = call_args[0][0]
        assert merged_config.default_timeout == 30


class TestNoLlmClient:
    """Toolkit without LLM client raises appropriately."""

    @pytest.mark.asyncio
    async def test_plan_create_without_llm_raises(self, tmp_path):
        """plan_create without llm_client raises RuntimeError."""
        tk = WebScrapingToolkit(
            headless=True,
            plans_dir=tmp_path / "plans",
        )
        with pytest.raises(RuntimeError, match="No LLM client"):
            await tk.plan_create(SAMPLE_URL, SAMPLE_OBJECTIVE)

    @pytest.mark.asyncio
    async def test_scrape_auto_generate_without_llm_raises(self, tmp_path):
        """scrape with objective but no LLM client raises RuntimeError."""
        tk = WebScrapingToolkit(
            headless=True,
            plans_dir=tmp_path / "plans",
        )
        with pytest.raises(RuntimeError, match="No LLM client"):
            await tk.scrape(SAMPLE_URL, objective="Get stuff")
