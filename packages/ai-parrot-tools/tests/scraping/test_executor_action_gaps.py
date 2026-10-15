"""Hover and submit behavior through the standalone executor."""

import json
from unittest.mock import AsyncMock

import pytest

from parrot_tools.scraping import executor as executor_module
from parrot_tools.scraping.executor import execute_plan_steps
from parrot_tools.scraping.plan import ScrapingPlan


@pytest.fixture
def spy_driver() -> AsyncMock:
    """Build a driver that can complete result extraction."""
    driver = AsyncMock()
    driver.get_page_source.return_value = "<html></html>"
    driver.current_url = "http://x/"
    return driver


async def test_hover_css_calls_driver_hover(spy_driver: AsyncMock) -> None:
    """A hover step invokes its driver method and succeeds."""
    plan = ScrapingPlan(url="http://x/", objective="hover", steps=[{"action": "hover", "selector": "#x"}])

    result = await execute_plan_steps(spy_driver, plan=plan)

    spy_driver.hover.assert_awaited_once_with("#x", 10)
    assert result.success is True
    assert result.metadata["step_errors"] == []


async def test_hover_text_selector_builds_xpath(spy_driver: AsyncMock) -> None:
    """Text selectors are converted to the executor's XPath DSL."""
    plan = ScrapingPlan(
        url="http://x/",
        objective="hover",
        steps=[{"action": "hover", "selector": "Menu", "selector_type": "text"}],
    )

    await execute_plan_steps(spy_driver, plan=plan)

    spy_driver.hover.assert_awaited_once_with("//*[contains(text(), 'Menu')]", 10)


async def test_hover_xpath_and_css_pseudo_and_timeout(spy_driver: AsyncMock) -> None:
    """Hover preserves XPath and strips BeautifulSoup-only CSS pseudos."""
    xpath_plan = ScrapingPlan(
        url="http://x/",
        objective="hover",
        steps=[{"action": "hover", "selector": "//button[@id='x']", "selector_type": "xpath", "timeout": 3}],
    )
    await execute_plan_steps(spy_driver, plan=xpath_plan)
    spy_driver.hover.assert_awaited_once_with("//button[@id='x']", 3)

    spy_driver.hover.reset_mock()
    css_plan = ScrapingPlan(
        url="http://x/",
        objective="hover",
        steps=[{"action": "hover", "selector": "#menu:contains('Menu')"}],
    )
    await execute_plan_steps(spy_driver, plan=css_plan)
    spy_driver.hover.assert_awaited_once_with("#menu", 10)


async def test_submit_form_uses_request_submit(spy_driver: AsyncMock) -> None:
    """A form result from evaluation does not trigger a driver click."""
    spy_driver.evaluate.return_value = "form"
    plan = ScrapingPlan(url="http://x/", objective="submit", steps=[{"action": "submit", "selector": "#form"}])

    result = await execute_plan_steps(spy_driver, plan=plan)

    spy_driver.evaluate.assert_awaited_once()
    spy_driver.click.assert_not_awaited()
    assert result.success is True


async def test_submit_button_clicks(spy_driver: AsyncMock) -> None:
    """A non-form result from evaluation clicks the original selector."""
    spy_driver.evaluate.return_value = "click"
    plan = ScrapingPlan(
        url="http://x/",
        objective="submit",
        steps=[{"action": "submit", "selector": "button[type='submit']", "timeout": 4}],
    )

    await execute_plan_steps(spy_driver, plan=plan)

    spy_driver.click.assert_awaited_once_with("button[type='submit']", 4)


async def test_submit_missing_records_error(spy_driver: AsyncMock) -> None:
    """A missing submit target records an error and later steps still run."""
    spy_driver.evaluate.return_value = "missing"
    plan = ScrapingPlan(
        url="http://x/",
        objective="submit",
        steps=[
            {"action": "submit", "selector": "#missing"},
            {"action": "hover", "selector": "#later"},
        ],
    )

    result = await execute_plan_steps(spy_driver, plan=plan)

    assert result.success is True
    assert result.metadata["step_errors"][0]["action"] == "submit"
    spy_driver.hover.assert_awaited_once_with("#later", 10)


async def test_submit_waits_after(spy_driver: AsyncMock) -> None:
    """A configured post-submit selector is awaited with its own timeout."""
    spy_driver.evaluate.return_value = "click"
    plan = ScrapingPlan(
        url="http://x/",
        objective="submit",
        steps=[
            {
                "action": "submit",
                "selector": "#submit",
                "wait_after_submit": "#result",
                "wait_timeout": 7,
            }
        ],
    )

    await execute_plan_steps(spy_driver, plan=plan)

    spy_driver.wait_for_selector.assert_awaited_once_with("#result", 7)


async def test_submit_selector_is_json_embedded(spy_driver: AsyncMock) -> None:
    """Submit embeds special-character selectors in one portable expression."""
    selector = r"input[data-value='a\\b\"c']"
    spy_driver.evaluate.return_value = "click"
    plan = ScrapingPlan(url="http://x/", objective="submit", steps=[{"action": "submit", "selector": selector}])

    await execute_plan_steps(spy_driver, plan=plan)

    expression = spy_driver.evaluate.await_args.args[0]
    assert json.dumps(selector) in expression
    spy_driver.execute_script.assert_not_awaited()
    assert "requestSubmit" in expression
    assert "document.evaluate" in expression
