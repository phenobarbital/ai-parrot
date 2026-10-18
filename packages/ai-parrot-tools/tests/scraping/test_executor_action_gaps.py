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


async def test_submit_expression_has_no_leading_whitespace() -> None:
    """Selenium prefixes ``return `` to the expression; a leading newline would make it a bare return."""
    from unittest.mock import AsyncMock

    from parrot_tools.scraping.executor import _action_submit

    driver = AsyncMock()
    driver.evaluate.return_value = "form"
    action = type("A", (), {"selector": "#f", "timeout": 5, "wait_after_submit": None, "wait_timeout": 5})()
    await _action_submit(driver, action, 10)
    expression = driver.evaluate.call_args.args[0]
    assert expression == expression.strip()
    assert expression.startswith("(")


# ── FEAT-684 / issue:28c2e9573ce2 ─────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Menu", "'Menu'"),
        ("Don't", '"Don\'t"'),
        ('say "hi"', "'say \"hi\"'"),
        ("a'b\"c", "concat('a', \"'\", 'b\"c')"),
        ("') or ('1'='1", "\"') or ('1'='1\""),
    ],
)
def test_xpath_literal_quotes(value: str, expected: str) -> None:
    """Text is always quoted as one XPath literal, never closing it early."""
    assert executor_module._xpath_literal(value) == expected


async def test_hover_text_selector_escapes_quotes(spy_driver: AsyncMock) -> None:
    """A single quote in a text selector yields a valid XPath literal."""
    plan = ScrapingPlan(
        url="http://x/",
        objective="hover",
        steps=[{"action": "hover", "selector": "Don't miss", "selector_type": "text"}],
    )

    await execute_plan_steps(spy_driver, plan=plan)

    spy_driver.hover.assert_awaited_once_with('//*[contains(text(), "Don\'t miss")]', 10)


async def test_click_text_selector_escapes_mixed_quotes(spy_driver: AsyncMock) -> None:
    """Click's text branch shares the escaped locator, using concat() for mixed quotes."""
    plan = ScrapingPlan(
        url="http://x/",
        objective="click",
        steps=[{"action": "click", "selector": 'it\'s "new"', "selector_type": "text"}],
    )

    await execute_plan_steps(spy_driver, plan=plan)

    spy_driver.click.assert_awaited_once_with("//*[contains(text(), concat('it', \"'\", 's \"new\"'))]", 10)


async def test_type_focused_clear_first_clears_active_element(spy_driver: AsyncMock) -> None:
    """With no selector, clear_first clears document.activeElement before typing."""
    calls: list[str] = []
    spy_driver.evaluate.side_effect = lambda *_a, **_k: calls.append("evaluate") or True
    spy_driver.type_text.side_effect = lambda *_a, **_k: calls.append("type_text")
    plan = ScrapingPlan(
        url="http://x/",
        objective="type",
        steps=[{"action": "type", "text": "hello", "clear_first": True}],
    )

    result = await execute_plan_steps(spy_driver, plan=plan)

    assert result.metadata["step_errors"] == []
    assert calls == ["evaluate", "type_text"]
    expression = spy_driver.evaluate.await_args.args[0]
    assert "document.activeElement" in expression
    assert expression == expression.strip()


async def test_type_focused_without_clear_first_skips_evaluate(spy_driver: AsyncMock) -> None:
    """No clear is attempted unless clear_first is set; a selected element is left to the driver."""
    plan = ScrapingPlan(
        url="http://x/",
        objective="type",
        steps=[
            {"action": "type", "text": "a"},
            {"action": "type", "text": "b", "selector": "#q", "clear_first": True},
        ],
    )

    await execute_plan_steps(spy_driver, plan=plan)

    spy_driver.evaluate.assert_not_awaited()
    assert spy_driver.type_text.await_count == 2


async def test_submit_strips_soup_pseudos(spy_driver: AsyncMock) -> None:
    """BS4-only pseudos never reach querySelector or the follow-up click/wait."""
    spy_driver.evaluate.return_value = "click"
    plan = ScrapingPlan(
        url="http://x/",
        objective="submit",
        steps=[
            {
                "action": "submit",
                "selector": "form#f button:-soup-contains('Go')",
                "wait_after_submit": "div.result:has(span)",
            }
        ],
    )

    result = await execute_plan_steps(spy_driver, plan=plan)

    assert result.metadata["step_errors"] == []
    expression = spy_driver.evaluate.await_args.args[0]
    assert json.dumps("form#f button") in expression
    assert "soup-contains" not in expression
    spy_driver.click.assert_awaited_once_with("form#f button", 10)
    spy_driver.wait_for_selector.assert_awaited_once_with("div.result", 5)


async def test_submit_xpath_selector_untouched(spy_driver: AsyncMock) -> None:
    """XPath submit selectors are passed through verbatim."""
    spy_driver.evaluate.return_value = "click"
    xpath = "//button[contains(., 'Go')]"
    plan = ScrapingPlan(url="http://x/", objective="submit", steps=[{"action": "submit", "selector": xpath}])

    await execute_plan_steps(spy_driver, plan=plan)

    assert json.dumps(xpath) in spy_driver.evaluate.await_args.args[0]
    spy_driver.click.assert_awaited_once_with(xpath, 10)


async def test_submit_selector_empty_after_strip_records_error(spy_driver: AsyncMock) -> None:
    """A selector that is only a BS4 pseudo is a step error, not a querySelector call."""
    plan = ScrapingPlan(
        url="http://x/",
        objective="submit",
        steps=[{"action": "submit", "selector": ":-soup-contains('Go')"}],
    )

    result = await execute_plan_steps(spy_driver, plan=plan)

    assert result.metadata["step_errors"][0]["action"] == "submit"
    spy_driver.evaluate.assert_not_awaited()
    spy_driver.click.assert_not_awaited()
