# TASK-062: Driver Abstraction Integration Tests

**Feature**: FEAT-015 — PlaywrightDriver
**Spec**: `sdd/specs/scraping-playwrightdriver.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-056, TASK-057, TASK-058, TASK-059, TASK-060, TASK-061
**Assigned-to**: claude-session

---

## Context

> This task implements Module 7 from the spec: end-to-end integration tests
> that validate the entire driver abstraction layer works together. These tests
> verify the factory lifecycle, driver swap transparency, backward compatibility,
> public exports, and configuration round-trips — ensuring all pieces from
> TASK-056 through TASK-061 compose correctly as a system.

---

## Scope

- Write integration tests covering:
  - **Factory lifecycle**: `DriverFactory.create() → driver.start() → driver.quit()`
    for both Selenium and Playwright paths
  - **Driver swap transparency**: Same test scenario works identically when
    switching between `driver_type="selenium"` and `driver_type="playwright"`
  - **Backward compatibility**: `WebScrapingTool` with no new params behaves
    as it did before FEAT-015
  - **Public exports**: All new classes are importable from `parrot.tools.scraping`
    and `parrot.tools.scraping.drivers`
  - **Config round-trip**: `PlaywrightConfig` → `DriverFactory.create()` →
    driver has expected config values
- All tests must use mocked browser backends (no real browsers required)

**NOT in scope**: Performance tests, real browser tests, anti-detection tests,
modifying any implementation code

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/tools/scraping/test_driver_integration.py` | CREATE | End-to-end integration tests |

---

## Implementation Notes

### Pattern to Follow

```python
# tests/tools/scraping/test_driver_integration.py
"""Integration tests for the driver abstraction layer (FEAT-015).

These tests verify that all driver components — AbstractDriver, PlaywrightDriver,
SeleniumDriver, PlaywrightConfig, DriverFactory, and WebScrapingTool integration —
compose correctly as a system.

All browser backends are mocked; no real browsers are required.
"""
```

### Key Constraints

- **No real browsers**: Mock all Playwright and Selenium APIs
- **Test the seams**: Focus on component interactions, not internal logic
  (unit tests in earlier tasks cover internals)
- **Parametrize where possible**: Use `@pytest.mark.parametrize` for tests
  that should pass with both driver types
- **Clean teardown**: Ensure `quit()` is always called even if test fails
  (use fixtures with yield)

### References in Codebase

- `tests/tools/scraping/test_abstract_driver.py` (TASK-056) — ABC tests
- `tests/tools/scraping/test_playwright_driver.py` (TASK-058) — Playwright unit tests
- `tests/tools/scraping/test_selenium_driver.py` (TASK-059) — Selenium unit tests
- `tests/tools/scraping/test_driver_factory.py` (TASK-060) — Factory unit tests
- `tests/tools/scraping/test_tool_driver_integration.py` (TASK-061) — Tool integration tests

---

## Acceptance Criteria

- [ ] Factory lifecycle test passes for Selenium path
- [ ] Factory lifecycle test passes for Playwright path
- [ ] Driver swap transparency test shows both drivers produce same interface
- [ ] Backward compatibility test confirms `WebScrapingTool()` default behavior unchanged
- [ ] All public exports from `parrot.tools.scraping` and `parrot.tools.scraping.drivers` verified
- [ ] Config round-trip test validates PlaywrightConfig values survive factory creation
- [ ] All tests pass: `pytest tests/tools/scraping/test_driver_integration.py -v`
- [ ] No linting errors: `ruff check tests/tools/scraping/test_driver_integration.py`

---

## Test Specification

```python
# tests/tools/scraping/test_driver_integration.py
"""Integration tests for FEAT-015 driver abstraction layer."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from parrot.tools.scraping.drivers.abstract import AbstractDriver
from parrot.tools.scraping.drivers.playwright_config import PlaywrightConfig
from parrot.tools.scraping.driver_factory import DriverFactory


class TestFactoryLifecycleSelenium:
    """Test full lifecycle: create → start → use → quit for Selenium."""

    def test_factory_returns_abstract_driver(self):
        driver = DriverFactory.create({"driver_type": "selenium"})
        assert isinstance(driver, AbstractDriver)

    @pytest.mark.asyncio
    @patch("parrot.tools.scraping.drivers.selenium_driver.SeleniumSetup")
    async def test_start_and_quit(self, mock_setup_cls):
        mock_instance = MagicMock()
        mock_instance.get_driver.return_value = MagicMock()
        mock_setup_cls.return_value = mock_instance

        driver = DriverFactory.create({"driver_type": "selenium"})
        await driver.start()
        assert driver._driver is not None
        await driver.quit()
        assert driver._driver is None


class TestFactoryLifecyclePlaywright:
    """Test full lifecycle: create → start → use → quit for Playwright."""

    def test_factory_returns_abstract_driver(self):
        driver = DriverFactory.create({"driver_type": "playwright"})
        assert isinstance(driver, AbstractDriver)

    @pytest.mark.asyncio
    async def test_start_and_quit(self):
        mock_pw = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()

        mock_pw.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        driver = DriverFactory.create({"driver_type": "playwright"})
        with patch(
            "parrot.tools.scraping.drivers.playwright_driver.async_playwright"
        ) as mock_apw:
            mock_apw.return_value.start = AsyncMock(return_value=mock_pw)
            await driver.start()

        assert driver._page is not None
        await driver.quit()


class TestDriverSwapTransparency:
    """Both drivers expose the same AbstractDriver interface."""

    @pytest.mark.parametrize("driver_type", ["selenium", "playwright"])
    def test_both_are_abstract_driver(self, driver_type):
        driver = DriverFactory.create({"driver_type": driver_type})
        assert isinstance(driver, AbstractDriver)

    @pytest.mark.parametrize("driver_type", ["selenium", "playwright"])
    def test_both_have_all_abstract_methods(self, driver_type):
        driver = DriverFactory.create({"driver_type": driver_type})
        for method_name in [
            "start", "quit", "navigate", "go_back", "go_forward", "reload",
            "click", "fill", "select_option", "hover", "press_key",
            "get_page_source", "get_text", "get_attribute", "get_all_texts",
            "screenshot", "wait_for_selector", "wait_for_navigation",
            "wait_for_load_state", "execute_script", "evaluate",
        ]:
            assert hasattr(driver, method_name), f"Missing method: {method_name}"
            assert callable(getattr(driver, method_name))


class TestBackwardCompatibility:
    """WebScrapingTool default behavior unchanged after FEAT-015."""

    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_default_tool_uses_selenium(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_driver = MagicMock(spec=AbstractDriver)
        mock_factory.create.return_value = mock_driver

        tool = WebScrapingTool()
        call_config = mock_factory.create.call_args[0][0]
        assert call_config["driver_type"] == "selenium"
        assert call_config["headless"] is True


class TestPublicExports:
    """All driver-related classes are importable from public packages."""

    def test_scraping_package_exports(self):
        from parrot.tools.scraping import (
            DriverFactory,
            AbstractDriver,
            PlaywrightDriver,
            SeleniumDriver,
            PlaywrightConfig,
        )
        assert all([
            DriverFactory, AbstractDriver, PlaywrightDriver,
            SeleniumDriver, PlaywrightConfig,
        ])

    def test_drivers_subpackage_exports(self):
        from parrot.tools.scraping.drivers import AbstractDriver as AD
        assert AD is not None

    def test_individual_module_imports(self):
        from parrot.tools.scraping.drivers.abstract import AbstractDriver
        from parrot.tools.scraping.drivers.playwright_driver import PlaywrightDriver
        from parrot.tools.scraping.drivers.playwright_config import PlaywrightConfig
        from parrot.tools.scraping.drivers.selenium_driver import SeleniumDriver
        from parrot.tools.scraping.driver_factory import DriverFactory
        assert all([
            AbstractDriver, PlaywrightDriver, PlaywrightConfig,
            SeleniumDriver, DriverFactory,
        ])


class TestConfigRoundTrip:
    """PlaywrightConfig values survive factory creation."""

    def test_config_values_in_driver(self):
        config = {
            "driver_type": "playwright",
            "browser": "firefox",
            "headless": False,
            "slow_mo": 50,
            "locale": "fr-FR",
        }
        driver = DriverFactory.create(config)
        assert driver.config.browser_type == "firefox"
        assert driver.config.headless is False
        assert driver.config.slow_mo == 50
        assert driver.config.locale == "fr-FR"

    def test_default_config_values(self):
        driver = DriverFactory.create({"driver_type": "playwright"})
        assert driver.config.browser_type == "chromium"
        assert driver.config.headless is True
        assert driver.config.slow_mo == 0

    def test_browser_mapping_in_config(self):
        """Edge maps to chromium in PlaywrightConfig."""
        driver = DriverFactory.create({
            "driver_type": "playwright",
            "browser": "edge",
        })
        assert driver.config.browser_type == "chromium"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scraping-playwrightdriver.spec.md` for full context
2. **Check dependencies** — ALL tasks TASK-056 through TASK-061 must be in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Review existing unit tests** in `tests/tools/scraping/` for patterns and coverage gaps
5. **Implement** following the scope and notes above
6. **Run the full test suite**: `pytest tests/tools/scraping/ -v`
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-062-driver-tests.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Created `tests/tools/scraping/test_driver_integration.py` with 26 integration
tests across 6 test classes: factory lifecycle (Selenium & Playwright), driver swap
transparency (parametrized), backward compatibility (WebScrapingTool), public exports
(package, subpackage, individual modules, `__all__`), and config round-trip (values,
defaults, browser mapping, viewport, selenium config). All 464 FEAT-015 scraping tests
passing. Two fixes were needed: (1) patching `playwright.async_api.async_playwright`
instead of module-level attribute since PlaywrightDriver uses lazy import, (2) checking
`current_url` as class-level property descriptor since accessing it on un-started
PlaywrightDriver raises (page is None).

**Deviations from spec**: Test spec suggested patching `parrot.tools.scraping.drivers.playwright_driver.async_playwright` for Playwright lifecycle test, but this fails because `async_playwright` is lazily imported inside `start()`. Fixed by patching at source: `playwright.async_api.async_playwright`. The `current_url` property test checks the class descriptor instead of `hasattr` on instance, since the property raises before `start()` is called.
