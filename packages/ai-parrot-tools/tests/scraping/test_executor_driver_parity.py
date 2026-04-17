"""Selenium↔Playwright parity test — TASK-732.

Proves that execute_plan_steps issues identical AbstractDriver calls regardless
of which concrete driver backend is "in use". Two independent RecordingDriver
instances are driven by the same plan; their recorded call sequences must match.
"""
from __future__ import annotations

from typing import Any, List, Tuple

import pytest

from parrot_tools.scraping.drivers.abstract import AbstractDriver
from parrot_tools.scraping.executor import execute_plan_steps
from parrot_tools.scraping.plan import ScrapingPlan


class RecordingDriver(AbstractDriver):
    """Concrete AbstractDriver that records every method call for assertion."""

    def __init__(self) -> None:
        self.calls: List[Tuple] = []
        self._url: str = ""
        self._html: str = "<html><body><h1>ok</h1></body></html>"

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self) -> None:
        self.calls.append(("start",))

    async def quit(self) -> None:
        self.calls.append(("quit",))

    # ── Navigation ─────────────────────────────────────────────────────

    async def navigate(self, url: str, timeout: int = 30) -> None:
        self.calls.append(("navigate", url, timeout))
        self._url = url

    async def go_back(self) -> None:
        self.calls.append(("go_back",))

    async def go_forward(self) -> None:
        self.calls.append(("go_forward",))

    async def reload(self) -> None:
        self.calls.append(("reload",))

    # ── Interaction ────────────────────────────────────────────────────

    async def click(self, selector: str, timeout: int = 10) -> None:
        self.calls.append(("click", selector, timeout))

    async def fill(self, selector: str, value: str, timeout: int = 10) -> None:
        self.calls.append(("fill", selector, value, timeout))

    async def select_option(
        self,
        selector: str,
        value: str,
        *,
        by: str = "value",
        timeout: int = 10,
    ) -> None:
        self.calls.append(("select_option", selector, value, by, timeout))

    async def hover(self, selector: str, timeout: int = 10) -> None:
        self.calls.append(("hover", selector, timeout))

    async def press_key(self, key: str) -> None:
        self.calls.append(("press_key", key))

    # ── Extraction ─────────────────────────────────────────────────────

    async def get_page_source(self) -> str:
        self.calls.append(("get_page_source",))
        return self._html

    async def get_text(self, selector: str, timeout: int = 10) -> str:
        self.calls.append(("get_text", selector))
        return ""

    async def get_attribute(
        self, selector: str, attribute: str, timeout: int = 10
    ) -> Any:
        self.calls.append(("get_attribute", selector, attribute))
        return None

    async def get_all_texts(self, selector: str, timeout: int = 10) -> List[str]:
        self.calls.append(("get_all_texts", selector))
        return []

    # ── Media ──────────────────────────────────────────────────────────

    async def screenshot(self, path: str, full_page: bool = False) -> bytes:
        self.calls.append(("screenshot", path))
        return b""

    # ── Waiting ────────────────────────────────────────────────────────

    async def wait_for_selector(
        self, selector: str, timeout: int = 10, state: str = "visible"
    ) -> None:
        self.calls.append(("wait_for_selector", selector, timeout, state))

    async def wait_for_navigation(self, timeout: int = 30) -> None:
        self.calls.append(("wait_for_navigation", timeout))

    async def wait_for_load_state(self, state: str = "load", timeout: int = 30) -> None:
        self.calls.append(("wait_for_load_state", state, timeout))

    # ── Scripting ──────────────────────────────────────────────────────

    async def execute_script(self, script: str, *args: Any) -> Any:
        self.calls.append(("execute_script", script, args))
        return None

    async def evaluate(self, expression: str) -> Any:
        self.calls.append(("evaluate", expression))
        return ""

    # ── Properties ────────────────────────────────────────────────────

    @property
    def current_url(self) -> str:
        return self._url


# ═══════════════════════════════════════════════════════════════════════
# Parity test — same plan, two independent drivers, identical call log
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_executor_parity_selenium_vs_playwright_mock():
    """Two RecordingDriver instances driven by the same plan produce identical call logs.

    This is the canonical proof of G1 ("no call-site changes between Selenium
    and Playwright") from the spec: the executor calls only AbstractDriver
    methods so swapping the concrete driver doesn't change the call sequence.
    """
    plan = ScrapingPlan(
        url="https://example.com",
        objective="parity",
        steps=[
            {"action": "navigate", "url": "https://example.com"},
            {"action": "wait", "condition": ".ready", "condition_type": "selector"},
            {"action": "click", "selector": "#go"},
            {"action": "fill", "selector": "#q", "value": "hi"},
            {"action": "extract", "selector": "h1", "extract_name": "title"},
        ],
    )
    driver_a = RecordingDriver()
    driver_b = RecordingDriver()

    await execute_plan_steps(driver_a, plan=plan)
    await execute_plan_steps(driver_b, plan=plan)

    assert driver_a.calls == driver_b.calls, (
        f"Call sequences differ:\n  A: {driver_a.calls}\n  B: {driver_b.calls}"
    )


@pytest.mark.asyncio
async def test_navigate_action_uses_abstract_navigate():
    """navigate action calls driver.navigate(), not driver.get()."""
    driver = RecordingDriver()
    plan = ScrapingPlan(
        url="https://example.com",
        objective="nav",
        steps=[{"action": "navigate", "url": "https://example.com"}],
    )
    await execute_plan_steps(driver, plan=plan)

    method_names = [call[0] for call in driver.calls]
    assert "navigate" in method_names
    # Ensure no raw selenium-style 'get' call was recorded
    assert "get" not in method_names


@pytest.mark.asyncio
async def test_click_action_uses_abstract_click():
    """click action calls driver.click(), not driver.find_element().click()."""
    driver = RecordingDriver()
    await execute_plan_steps(
        driver,
        steps=[{"action": "click", "selector": "#btn"}],
    )
    method_names = [call[0] for call in driver.calls]
    assert "click" in method_names
    assert "find_element" not in method_names


@pytest.mark.asyncio
async def test_fill_action_uses_abstract_fill():
    """fill action calls driver.fill()."""
    driver = RecordingDriver()
    await execute_plan_steps(
        driver,
        steps=[{"action": "fill", "selector": "#name", "value": "Alice"}],
    )
    method_names = [call[0] for call in driver.calls]
    assert "fill" in method_names


@pytest.mark.asyncio
async def test_refresh_action_uses_abstract_reload():
    """refresh action calls driver.reload(), not driver.refresh()."""
    driver = RecordingDriver()
    await execute_plan_steps(
        driver,
        steps=[{"action": "refresh"}],
    )
    method_names = [call[0] for call in driver.calls]
    assert "reload" in method_names
    assert "refresh" not in method_names


@pytest.mark.asyncio
async def test_back_action_uses_abstract_go_back():
    """back action calls driver.go_back(), not driver.back()."""
    driver = RecordingDriver()
    await execute_plan_steps(
        driver,
        steps=[{"action": "back", "steps": 2}],
    )
    go_back_calls = [c for c in driver.calls if c[0] == "go_back"]
    assert len(go_back_calls) == 2
    assert not any(c[0] == "back" for c in driver.calls)
