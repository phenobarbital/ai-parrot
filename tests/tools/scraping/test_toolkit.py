"""Tests for WebScrapingToolkit — TASK-053."""
import json

import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from parrot.tools.scraping.toolkit import WebScrapingToolkit
from parrot.tools.scraping.plan import ScrapingPlan
from parrot.tools.scraping.toolkit_models import (
    DriverConfig,
    PlanSaveResult,
    PlanSummary,
)


# ── Fixtures ──────────────────────────────────────────────────────────

VALID_PLAN_JSON = json.dumps({
    "url": "https://example.com/products",
    "objective": "Extract products",
    "steps": [
        {"action": "navigate", "url": "https://example.com/products"},
        {"action": "wait", "condition": ".product-list", "condition_type": "selector"},
    ],
})

HTML_BODY = "<html><body><h1>Test Page</h1><p class='info'>Content</p></body></html>"


@pytest.fixture
def mock_llm_client():
    client = AsyncMock()
    client.complete = AsyncMock(return_value=VALID_PLAN_JSON)
    return client


@pytest.fixture
def toolkit(tmp_path, mock_llm_client):
    return WebScrapingToolkit(
        headless=True,
        plans_dir=tmp_path / "plans",
        llm_client=mock_llm_client,
    )


@pytest.fixture
def toolkit_no_llm(tmp_path):
    return WebScrapingToolkit(
        headless=True,
        plans_dir=tmp_path / "plans",
    )


@pytest.fixture
def sample_plan():
    return ScrapingPlan(
        url="https://example.com/products",
        objective="Extract products",
        steps=[
            {"action": "navigate", "url": "https://example.com/products"},
            {"action": "wait", "condition": ".product-list", "condition_type": "selector"},
        ],
    )


@pytest.fixture
def mock_driver():
    driver = MagicMock()
    type(driver).current_url = PropertyMock(return_value="https://example.com/products")
    type(driver).page_source = PropertyMock(return_value=HTML_BODY)
    driver.get = MagicMock(return_value=None)
    driver.execute_script = MagicMock(return_value=None)
    driver.quit = MagicMock(return_value=None)
    return driver


# ── TestInheritance ───────────────────────────────────────────────────

class TestInheritance:
    def test_inherits_abstract_toolkit(self, toolkit):
        from parrot.tools.toolkit import AbstractToolkit

        assert isinstance(toolkit, AbstractToolkit)

    def test_get_tools_returns_seven(self, toolkit):
        tools = toolkit.get_tools()
        assert len(tools) == 7

    def test_tool_names(self, toolkit):
        names = toolkit.list_tool_names()
        expected = {
            "plan_create", "plan_save", "plan_load",
            "plan_list", "plan_delete", "scrape", "crawl",
        }
        assert set(names) == expected


# ── TestConstructor ───────────────────────────────────────────────────

class TestConstructor:
    def test_default_config(self, toolkit):
        assert toolkit._config.driver_type == "selenium"
        assert toolkit._config.headless is True
        assert toolkit._config.browser == "chrome"

    def test_custom_config(self, tmp_path, mock_llm_client):
        tk = WebScrapingToolkit(
            driver_type="playwright",
            browser="firefox",
            headless=False,
            plans_dir=tmp_path / "plans",
            llm_client=mock_llm_client,
        )
        assert tk._config.driver_type == "playwright"
        assert tk._config.browser == "firefox"
        assert tk._config.headless is False

    def test_session_based_flag(self, tmp_path, mock_llm_client):
        tk = WebScrapingToolkit(
            session_based=True,
            plans_dir=tmp_path / "plans",
            llm_client=mock_llm_client,
        )
        assert tk._session_based is True
        assert tk._session_driver is None


# ── TestLifecycle ─────────────────────────────────────────────────────

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_session_driver(self, tmp_path, mock_llm_client, mock_driver):
        tk = WebScrapingToolkit(
            session_based=True,
            plans_dir=tmp_path / "plans",
            llm_client=mock_llm_client,
        )
        mock_setup = MagicMock()
        mock_setup.get_driver = AsyncMock(return_value=mock_driver)

        from parrot.tools.scraping.driver_context import DriverRegistry

        original = DriverRegistry._factories.get("selenium")
        DriverRegistry.register("selenium", lambda cfg: mock_setup)
        try:
            await tk.start()
            assert tk._session_driver is mock_driver
        finally:
            if original:
                DriverRegistry.register("selenium", original)
            await tk.stop()

    @pytest.mark.asyncio
    async def test_start_noop_when_not_session(self, toolkit):
        await toolkit.start()
        assert toolkit._session_driver is None

    @pytest.mark.asyncio
    async def test_stop_clears_driver(self, tmp_path, mock_llm_client, mock_driver):
        tk = WebScrapingToolkit(
            session_based=True,
            plans_dir=tmp_path / "plans",
            llm_client=mock_llm_client,
        )
        tk._session_driver = mock_driver
        await tk.stop()
        assert tk._session_driver is None
        mock_driver.quit.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_noop_when_no_driver(self, toolkit):
        await toolkit.stop()  # should not raise


# ── TestPlanCreate ────────────────────────────────────────────────────

class TestPlanCreate:
    @pytest.mark.asyncio
    async def test_generates_plan_via_llm(self, toolkit):
        plan = await toolkit.plan_create(
            "https://example.com/products", "Extract products"
        )
        assert isinstance(plan, ScrapingPlan)
        assert plan.url == "https://example.com/products"

    @pytest.mark.asyncio
    async def test_returns_cached_plan(self, toolkit, sample_plan):
        # Save a plan first
        await toolkit.plan_save(sample_plan)
        # Now plan_create should return from cache
        plan = await toolkit.plan_create(
            "https://example.com/products", "Extract products"
        )
        assert isinstance(plan, ScrapingPlan)

    @pytest.mark.asyncio
    async def test_force_regenerate_bypasses_cache(self, toolkit, sample_plan):
        await toolkit.plan_save(sample_plan)
        plan = await toolkit.plan_create(
            "https://example.com/products",
            "Extract products",
            force_regenerate=True,
        )
        assert isinstance(plan, ScrapingPlan)
        # LLM client should have been called
        toolkit._llm_client.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_llm_client_raises(self, toolkit_no_llm):
        with pytest.raises(RuntimeError, match="No LLM client"):
            await toolkit_no_llm.plan_create("https://example.com", "test")


# ── TestPlanSave ──────────────────────────────────────────────────────

class TestPlanSave:
    @pytest.mark.asyncio
    async def test_saves_plan(self, toolkit, sample_plan):
        result = await toolkit.plan_save(sample_plan)
        assert isinstance(result, PlanSaveResult)
        assert result.success is True
        assert result.registered is True
        assert result.name == sample_plan.name

    @pytest.mark.asyncio
    async def test_duplicate_without_overwrite(self, toolkit, sample_plan):
        await toolkit.plan_save(sample_plan)
        result = await toolkit.plan_save(sample_plan)
        assert result.success is False
        assert "already exists" in result.message

    @pytest.mark.asyncio
    async def test_duplicate_with_overwrite(self, toolkit, sample_plan):
        await toolkit.plan_save(sample_plan)
        result = await toolkit.plan_save(sample_plan, overwrite=True)
        assert result.success is True


# ── TestPlanLoad ──────────────────────────────────────────────────────

class TestPlanLoad:
    @pytest.mark.asyncio
    async def test_load_by_url(self, toolkit, sample_plan):
        await toolkit.plan_save(sample_plan)
        loaded = await toolkit.plan_load("https://example.com/products")
        assert loaded is not None
        assert loaded.url == sample_plan.url

    @pytest.mark.asyncio
    async def test_load_by_name(self, toolkit, sample_plan):
        await toolkit.plan_save(sample_plan)
        loaded = await toolkit.plan_load(sample_plan.name)
        assert loaded is not None

    @pytest.mark.asyncio
    async def test_load_nonexistent(self, toolkit):
        loaded = await toolkit.plan_load("nonexistent")
        assert loaded is None


# ── TestPlanList ──────────────────────────────────────────────────────

class TestPlanList:
    @pytest.mark.asyncio
    async def test_empty_list(self, toolkit):
        plans = await toolkit.plan_list()
        assert plans == []

    @pytest.mark.asyncio
    async def test_list_with_plan(self, toolkit, sample_plan):
        await toolkit.plan_save(sample_plan)
        plans = await toolkit.plan_list()
        assert len(plans) == 1
        assert isinstance(plans[0], PlanSummary)
        assert plans[0].url == sample_plan.url

    @pytest.mark.asyncio
    async def test_filter_by_domain(self, toolkit, sample_plan):
        await toolkit.plan_save(sample_plan)
        plans = await toolkit.plan_list(domain_filter="example.com")
        assert len(plans) == 1
        plans = await toolkit.plan_list(domain_filter="other.com")
        assert len(plans) == 0

    @pytest.mark.asyncio
    async def test_filter_by_tag(self, toolkit):
        plan = ScrapingPlan(
            url="https://example.com/products",
            objective="Extract products",
            steps=[{"action": "navigate", "url": "https://example.com/products"}],
            tags=["ecommerce", "products"],
        )
        await toolkit.plan_save(plan)
        plans = await toolkit.plan_list(tag_filter="ecommerce")
        assert len(plans) == 1
        plans = await toolkit.plan_list(tag_filter="news")
        assert len(plans) == 0


# ── TestPlanDelete ────────────────────────────────────────────────────

class TestPlanDelete:
    @pytest.mark.asyncio
    async def test_delete_existing(self, toolkit, sample_plan):
        await toolkit.plan_save(sample_plan)
        result = await toolkit.plan_delete(sample_plan.name)
        assert result is True
        # Verify it's gone
        loaded = await toolkit.plan_load(sample_plan.name)
        assert loaded is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, toolkit):
        result = await toolkit.plan_delete("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_without_file(self, toolkit, sample_plan):
        await toolkit.plan_save(sample_plan)
        result = await toolkit.plan_delete(sample_plan.name, delete_file=False)
        assert result is True


# ── TestScrape ────────────────────────────────────────────────────────

class TestScrape:
    @pytest.mark.asyncio
    async def test_scrape_with_explicit_plan(self, toolkit, sample_plan, mock_driver):
        with patch(
            "parrot.tools.scraping.toolkit.driver_context"
        ) as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_driver)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await toolkit.scrape(
                "https://example.com/products",
                plan=sample_plan,
            )
            assert result is not None
            assert result.url == "https://example.com/products"

    @pytest.mark.asyncio
    async def test_scrape_with_raw_steps(self, toolkit, mock_driver):
        with patch(
            "parrot.tools.scraping.toolkit.driver_context"
        ) as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_driver)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await toolkit.scrape(
                "https://example.com",
                steps=[{"action": "navigate", "url": "https://example.com"}],
            )
            assert result is not None
            mock_driver.get.assert_called()

    @pytest.mark.asyncio
    async def test_scrape_with_cached_plan(self, toolkit, sample_plan, mock_driver):
        await toolkit.plan_save(sample_plan)
        with patch(
            "parrot.tools.scraping.toolkit.driver_context"
        ) as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_driver)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await toolkit.scrape("https://example.com/products")
            assert result is not None

    @pytest.mark.asyncio
    async def test_scrape_auto_generate(self, toolkit, mock_driver):
        with patch(
            "parrot.tools.scraping.toolkit.driver_context"
        ) as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_driver)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await toolkit.scrape(
                "https://example.com/products",
                objective="Extract products",
            )
            assert result is not None
            toolkit._llm_client.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_scrape_no_plan_raises(self, toolkit_no_llm):
        with pytest.raises(ValueError, match="No plan available"):
            await toolkit_no_llm.scrape("https://example.com")

    @pytest.mark.asyncio
    async def test_scrape_with_plan_dict(self, toolkit, mock_driver):
        plan_dict = {
            "url": "https://example.com",
            "objective": "Test",
            "steps": [{"action": "navigate", "url": "https://example.com"}],
        }
        with patch(
            "parrot.tools.scraping.toolkit.driver_context"
        ) as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_driver)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await toolkit.scrape(
                "https://example.com",
                plan=plan_dict,
            )
            assert result is not None


# ── TestCrawl ─────────────────────────────────────────────────────────

class TestCrawl:
    @pytest.mark.asyncio
    async def test_crawl_not_implemented(self, toolkit):
        """crawl() raises NotImplementedError if CrawlEngine unavailable."""
        with pytest.raises((NotImplementedError, ValueError)):
            await toolkit.crawl("https://example.com")


# ── TestPlanResolution ────────────────────────────────────────────────

class TestPlanResolution:
    @pytest.mark.asyncio
    async def test_explicit_plan_has_priority(self, toolkit, sample_plan):
        # Save a different plan
        other = ScrapingPlan(
            url="https://example.com/products",
            objective="Other objective",
            steps=[{"action": "navigate", "url": "https://example.com/products"}],
        )
        await toolkit.plan_save(other)

        resolved = await toolkit._resolve_plan(
            "https://example.com/products", plan=sample_plan
        )
        assert resolved.objective == "Extract products"

    @pytest.mark.asyncio
    async def test_cache_lookup(self, toolkit, sample_plan):
        await toolkit.plan_save(sample_plan)
        resolved = await toolkit._resolve_plan("https://example.com/products")
        assert resolved.url == sample_plan.url

    @pytest.mark.asyncio
    async def test_auto_generate_with_objective(self, toolkit):
        resolved = await toolkit._resolve_plan(
            "https://example.com/products",
            objective="Extract products",
        )
        assert isinstance(resolved, ScrapingPlan)
        toolkit._llm_client.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_plan_raises(self, toolkit_no_llm):
        with pytest.raises(ValueError, match="No plan available"):
            await toolkit_no_llm._resolve_plan("https://example.com")

    @pytest.mark.asyncio
    async def test_dict_plan_resolved(self, toolkit):
        plan_dict = {
            "url": "https://example.com",
            "objective": "Test",
            "steps": [{"action": "navigate", "url": "https://example.com"}],
        }
        resolved = await toolkit._resolve_plan(
            "https://example.com", plan=plan_dict
        )
        assert isinstance(resolved, ScrapingPlan)
        assert resolved.url == "https://example.com"


# ── TestEnsureRegistry ────────────────────────────────────────────────

class TestEnsureRegistry:
    @pytest.mark.asyncio
    async def test_lazy_loading(self, toolkit):
        assert toolkit._registry is None
        reg = await toolkit._ensure_registry()
        assert reg is not None
        # Second call returns same instance
        reg2 = await toolkit._ensure_registry()
        assert reg is reg2
