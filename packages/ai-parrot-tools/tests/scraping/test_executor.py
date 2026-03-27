"""Tests for Step Executor — TASK-051."""
import asyncio
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from parrot.tools.scraping.executor import (
    _apply_selectors,
    _dispatch_step,
    _get_current_url,
    _get_page_source,
    execute_plan_steps,
)
from parrot.tools.scraping.models import ScrapingSelector, ScrapingStep
from parrot.tools.scraping.plan import ScrapingPlan
from parrot.tools.scraping.toolkit_models import DriverConfig


# ── Fixtures ──────────────────────────────────────────────────────────

HTML_BODY = "<html><body><h1>Title</h1><p class='desc'>Hello world</p></body></html>"


@pytest.fixture
def mock_driver():
    """A mock Selenium-like driver."""
    driver = MagicMock()
    type(driver).current_url = PropertyMock(return_value="https://example.com")
    type(driver).page_source = PropertyMock(return_value=HTML_BODY)
    driver.get = MagicMock(return_value=None)
    driver.refresh = MagicMock(return_value=None)
    driver.back = MagicMock(return_value=None)
    driver.execute_script = MagicMock(return_value=None)
    driver.save_screenshot = MagicMock(return_value=None)
    active_el = MagicMock()
    driver.switch_to.active_element = active_el
    return driver


@pytest.fixture
def sample_plan():
    return ScrapingPlan(
        url="https://example.com",
        objective="Test",
        steps=[
            {"action": "navigate", "url": "https://example.com"},
            {"action": "wait", "condition": "h1", "condition_type": "selector"},
        ],
    )


@pytest.fixture
def sample_plan_with_selectors():
    return ScrapingPlan(
        url="https://example.com",
        objective="Extract title",
        steps=[
            {"action": "navigate", "url": "https://example.com"},
        ],
        selectors=[
            {"name": "title", "selector": "h1", "extract_type": "text"},
            {"name": "desc", "selector": ".desc", "extract_type": "text"},
        ],
    )


# ── TestExecutePlanSteps ──────────────────────────────────────────────

class TestExecutePlanSteps:
    @pytest.mark.asyncio
    async def test_executes_steps_from_plan(self, mock_driver, sample_plan):
        """Steps from a ScrapingPlan are executed."""
        result = await execute_plan_steps(mock_driver, plan=sample_plan)
        assert result is not None
        assert result.url == "https://example.com"
        mock_driver.get.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_executes_raw_steps(self, mock_driver):
        """Raw step dicts execute without a ScrapingPlan."""
        result = await execute_plan_steps(
            mock_driver,
            steps=[{"action": "navigate", "url": "https://example.com"}],
            base_url="https://example.com",
        )
        assert result is not None
        assert result.success is True
        mock_driver.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_scraping_result(self, mock_driver, sample_plan):
        """Result is a proper ScrapingResult."""
        from parrot.tools.scraping.models import ScrapingResult as SR

        result = await execute_plan_steps(mock_driver, plan=sample_plan)
        assert isinstance(result, SR)
        assert result.content == HTML_BODY
        assert result.bs_soup is not None

    @pytest.mark.asyncio
    async def test_selector_extraction(self, mock_driver, sample_plan_with_selectors):
        """Selectors extract data from the page source."""
        result = await execute_plan_steps(
            mock_driver, plan=sample_plan_with_selectors
        )
        assert result.extracted_data["title"] == "Title"
        assert result.extracted_data["desc"] == "Hello world"

    @pytest.mark.asyncio
    async def test_handles_step_failure_gracefully(self, mock_driver, sample_plan):
        """Failed non-critical step is captured but doesn't abort."""
        plan = ScrapingPlan(
            url="https://example.com",
            objective="Test failure",
            steps=[
                {"action": "navigate", "url": "https://example.com"},
                {"action": "scroll", "direction": "down"},
                {"action": "scroll", "direction": "down"},
            ],
        )
        # Make scroll fail on the first call
        mock_driver.execute_script.side_effect = [
            Exception("Scroll error"),
            None,  # second scroll succeeds
        ]
        result = await execute_plan_steps(
            mock_driver, plan=plan, config=DriverConfig(delay_between_actions=0)
        )
        # The plan continues despite the error
        assert result.success is True
        assert len(result.metadata["step_errors"]) == 1
        assert result.metadata["step_errors"][0]["step_index"] == 1

    @pytest.mark.asyncio
    async def test_critical_failure_aborts(self, mock_driver):
        """Navigate failure aborts remaining steps."""
        plan = ScrapingPlan(
            url="https://example.com",
            objective="Test abort",
            steps=[
                {"action": "navigate", "url": "https://example.com"},
                {"action": "scroll", "direction": "down"},
            ],
        )
        mock_driver.get.side_effect = Exception("Network error")
        result = await execute_plan_steps(
            mock_driver, plan=plan, config=DriverConfig(delay_between_actions=0)
        )
        assert result.success is False
        assert result.metadata["aborted"] is True
        # Scroll should not have been attempted
        mock_driver.execute_script.assert_not_called()

    @pytest.mark.asyncio
    async def test_delay_between_steps(self, mock_driver):
        """Configurable delay is applied between steps."""
        plan = ScrapingPlan(
            url="https://example.com",
            objective="Test delay",
            steps=[
                {"action": "navigate", "url": "https://example.com"},
                {"action": "scroll", "direction": "down"},
            ],
        )
        config = DriverConfig(delay_between_actions=0.05)
        start = time.monotonic()
        await execute_plan_steps(mock_driver, plan=plan, config=config)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.04  # at least ~50ms delay

    @pytest.mark.asyncio
    async def test_empty_steps(self, mock_driver):
        """Empty steps list returns success with empty result."""
        result = await execute_plan_steps(mock_driver, steps=[])
        assert result.success is True
        assert result.metadata["total_steps"] == 0

    @pytest.mark.asyncio
    async def test_plan_takes_priority_over_raw_steps(self, mock_driver, sample_plan):
        """When both plan and steps are provided, plan wins."""
        result = await execute_plan_steps(
            mock_driver,
            plan=sample_plan,
            steps=[{"action": "scroll", "direction": "top"}],
        )
        # Plan has navigate + wait; raw steps would have scroll
        mock_driver.get.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_raw_selectors_extraction(self, mock_driver):
        """Raw selectors (no plan) extract data."""
        result = await execute_plan_steps(
            mock_driver,
            steps=[{"action": "navigate", "url": "https://example.com"}],
            selectors=[
                {"name": "heading", "selector": "h1", "extract_type": "text"},
            ],
            base_url="https://example.com",
        )
        assert result.extracted_data["heading"] == "Title"

    @pytest.mark.asyncio
    async def test_page_source_failure(self, mock_driver, sample_plan):
        """Failure to get page source returns error result."""
        type(mock_driver).page_source = PropertyMock(side_effect=Exception("Session dead"))
        result = await execute_plan_steps(
            mock_driver, plan=sample_plan, config=DriverConfig(delay_between_actions=0)
        )
        assert result.success is False
        assert "page" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_metadata_contains_step_info(self, mock_driver, sample_plan):
        """Result metadata includes step execution info."""
        result = await execute_plan_steps(
            mock_driver, plan=sample_plan, config=DriverConfig(delay_between_actions=0)
        )
        assert result.metadata["total_steps"] == 2
        assert result.metadata["aborted"] is False
        assert "timestamp" in result.metadata


# ── TestDispatchStep ──────────────────────────────────────────────────

class TestDispatchStep:
    @pytest.mark.asyncio
    async def test_navigate(self, mock_driver):
        step = ScrapingStep.from_dict({"action": "navigate", "url": "https://test.com"})
        result = await _dispatch_step(mock_driver, step, "", 10)
        assert result is True
        mock_driver.get.assert_called_once_with("https://test.com")

    @pytest.mark.asyncio
    async def test_navigate_with_base_url(self, mock_driver):
        step = ScrapingStep.from_dict({"action": "navigate", "url": "/page"})
        result = await _dispatch_step(mock_driver, step, "https://base.com", 10)
        assert result is True
        mock_driver.get.assert_called_once_with("https://base.com/page")

    @pytest.mark.asyncio
    async def test_scroll_down(self, mock_driver):
        step = ScrapingStep.from_dict({"action": "scroll", "direction": "down", "amount": 300})
        result = await _dispatch_step(mock_driver, step, "", 10)
        assert result is True
        mock_driver.execute_script.assert_called_once_with("window.scrollBy(0, 300);")

    @pytest.mark.asyncio
    async def test_scroll_top(self, mock_driver):
        step = ScrapingStep.from_dict({"action": "scroll", "direction": "top"})
        result = await _dispatch_step(mock_driver, step, "", 10)
        assert result is True
        mock_driver.execute_script.assert_called_once_with("window.scrollTo(0, 0);")

    @pytest.mark.asyncio
    async def test_evaluate_js(self, mock_driver):
        step = ScrapingStep.from_dict({"action": "evaluate", "script": "return 1+1;"})
        result = await _dispatch_step(mock_driver, step, "", 10)
        assert result is True
        mock_driver.execute_script.assert_called_once_with("return 1+1;")

    @pytest.mark.asyncio
    async def test_refresh(self, mock_driver):
        step = ScrapingStep.from_dict({"action": "refresh"})
        result = await _dispatch_step(mock_driver, step, "", 10)
        assert result is True
        mock_driver.refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_back(self, mock_driver):
        step = ScrapingStep.from_dict({"action": "back", "steps": 2})
        result = await _dispatch_step(mock_driver, step, "", 10)
        assert result is True
        assert mock_driver.back.call_count == 2

    @pytest.mark.asyncio
    async def test_unknown_action_returns_false(self, mock_driver):
        """Unknown action logged and returns False."""
        step = MagicMock()
        step.action.get_action_type.return_value = "nonexistent_action"
        step.description = "test"
        result = await _dispatch_step(mock_driver, step, "", 10)
        assert result is False

    @pytest.mark.asyncio
    async def test_advanced_actions_skip_gracefully(self, mock_driver):
        """Advanced actions (loop, conditional, etc.) skip with warning."""
        step = MagicMock()
        step.action.get_action_type.return_value = "loop"
        step.description = "test loop"
        result = await _dispatch_step(mock_driver, step, "", 10)
        assert result is True  # does not block pipeline


# ── TestApplySelectors ────────────────────────────────────────────────

class TestApplySelectors:
    def test_css_text_extraction(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(HTML_BODY, "html.parser")
        selectors = [
            ScrapingSelector(name="title", selector="h1", extract_type="text"),
        ]
        result = _apply_selectors(soup, selectors)
        assert result["title"] == "Title"

    def test_css_html_extraction(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(HTML_BODY, "html.parser")
        selectors = [
            ScrapingSelector(name="heading", selector="h1", extract_type="html"),
        ]
        result = _apply_selectors(soup, selectors)
        assert "<h1>" in result["heading"]

    def test_multiple_elements(self):
        from bs4 import BeautifulSoup

        html = "<html><body><li>A</li><li>B</li><li>C</li></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        selectors = [
            ScrapingSelector(name="items", selector="li", extract_type="text", multiple=True),
        ]
        result = _apply_selectors(soup, selectors)
        assert result["items"] == ["A", "B", "C"]

    def test_single_from_multiple(self):
        from bs4 import BeautifulSoup

        html = "<html><body><li>A</li><li>B</li></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        selectors = [
            ScrapingSelector(name="first", selector="li", extract_type="text", multiple=False),
        ]
        result = _apply_selectors(soup, selectors)
        assert result["first"] == "A"

    def test_attribute_extraction(self):
        from bs4 import BeautifulSoup

        html = '<html><body><a href="/link">Link</a></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        selectors = [
            ScrapingSelector(
                name="link",
                selector="a",
                extract_type="attribute",
                attribute="href",
            ),
        ]
        result = _apply_selectors(soup, selectors)
        assert result["link"] == "/link"

    def test_no_match_returns_empty(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(HTML_BODY, "html.parser")
        selectors = [
            ScrapingSelector(name="missing", selector=".nonexistent", extract_type="text"),
        ]
        result = _apply_selectors(soup, selectors)
        assert result["missing"] == ""

    def test_tag_selector_type(self):
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(HTML_BODY, "html.parser")
        selectors = [
            ScrapingSelector(
                name="paragraphs", selector="p", selector_type="tag",
                extract_type="text", multiple=True,
            ),
        ]
        result = _apply_selectors(soup, selectors)
        assert "Hello world" in result["paragraphs"]


# ── TestHelpers ───────────────────────────────────────────────────────

class TestHelpers:
    @pytest.mark.asyncio
    async def test_get_current_url(self, mock_driver):
        url = await _get_current_url(mock_driver)
        assert url == "https://example.com"

    @pytest.mark.asyncio
    async def test_get_page_source(self, mock_driver):
        source = await _get_page_source(mock_driver)
        assert source == HTML_BODY
