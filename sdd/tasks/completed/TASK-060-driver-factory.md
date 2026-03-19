# TASK-060: DriverFactory

**Feature**: FEAT-015 — PlaywrightDriver
**Spec**: `sdd/specs/scraping-playwrightdriver.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-056, TASK-058, TASK-059
**Assigned-to**: unassigned

---

## Context

> This task implements Module 5 from the spec: the `DriverFactory` that
> dispatches driver creation based on configuration. It is the single entry
> point for obtaining a properly configured `AbstractDriver` instance.
> `WebScrapingTool` and other consumers use `DriverFactory.create()` instead
> of directly instantiating driver classes.

---

## Scope

- Implement `DriverFactory` class with:
  - `create(config) -> AbstractDriver` — static method that inspects config to
    determine which driver to instantiate and returns it
  - `_map_browser_to_playwright(browser: str) -> str` — helper that maps
    generic browser names to Playwright browser types:
    - `"chrome"` / `"chromium"` → `"chromium"`
    - `"firefox"` → `"firefox"`
    - `"safari"` / `"webkit"` → `"webkit"`
    - `"edge"` → `"chromium"` (Edge is Chromium-based)
    - Unknown → raise `ValueError`
- Update `parrot/tools/scraping/__init__.py` to export `DriverFactory`
- Write unit tests

**NOT in scope**: WebScrapingTool integration (TASK-061), driver implementations
(TASK-058, TASK-059)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/driver_factory.py` | CREATE | `DriverFactory` with `create()` static method |
| `parrot/tools/scraping/__init__.py` | MODIFY | Add `DriverFactory` to exports |
| `tests/tools/scraping/test_driver_factory.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow

```python
import logging
from typing import Any, Dict, Optional, Union

from parrot.tools.scraping.drivers.abstract import AbstractDriver

logger = logging.getLogger(__name__)

# Browser name → Playwright browser type mapping
_BROWSER_TO_PLAYWRIGHT = {
    "chrome": "chromium",
    "chromium": "chromium",
    "firefox": "firefox",
    "safari": "webkit",
    "webkit": "webkit",
    "edge": "chromium",
}


class DriverFactory:
    """Factory for creating browser automation driver instances.

    Dispatches to the correct driver implementation based on configuration.
    This is the single entry point for obtaining an AbstractDriver.

    Usage:
        driver = DriverFactory.create({"driver_type": "playwright", "browser": "chromium"})
        await driver.start()
    """

    @staticmethod
    def create(
        config: Optional[Union[Dict[str, Any], "DriverConfig"]] = None,
    ) -> AbstractDriver:
        """Create and return an AbstractDriver based on configuration.

        Args:
            config: Driver configuration. Can be a dict or a DriverConfig instance.
                    If None, defaults to SeleniumDriver with chrome.
                    Key fields:
                    - driver_type: "selenium" or "playwright" (default: "selenium")
                    - browser: Browser name (default: "chrome")
                    - headless: Whether to run headless (default: True)
                    - Plus driver-specific options.

        Returns:
            An AbstractDriver instance (not yet started — caller must await start()).

        Raises:
            ValueError: If driver_type is unknown or browser name is invalid.
        """
        if config is None:
            config = {}

        # Normalize dict-like access
        if hasattr(config, "model_dump"):
            config = config.model_dump()
        elif hasattr(config, "__dataclass_fields__"):
            from dataclasses import asdict
            config = asdict(config)

        driver_type = config.get("driver_type", "selenium")
        browser = config.get("browser", "chrome")
        headless = config.get("headless", True)

        if driver_type == "playwright":
            from parrot.tools.scraping.drivers.playwright_driver import PlaywrightDriver
            from parrot.tools.scraping.drivers.playwright_config import PlaywrightConfig

            pw_browser = DriverFactory._map_browser_to_playwright(browser)
            pw_config = PlaywrightConfig(
                browser_type=pw_browser,
                headless=headless,
                slow_mo=config.get("slow_mo", 0),
                timeout=config.get("default_timeout", 30),
                viewport=config.get("viewport"),
                locale=config.get("locale"),
                timezone=config.get("timezone"),
                proxy=config.get("proxy"),
                mobile=config.get("mobile", False),
                device_name=config.get("device_name"),
                ignore_https_errors=config.get("ignore_https_errors", False),
                storage_state=config.get("storage_state"),
            )
            logger.info("Creating PlaywrightDriver (browser=%s)", pw_browser)
            return PlaywrightDriver(pw_config)

        elif driver_type == "selenium":
            from parrot.tools.scraping.drivers.selenium_driver import SeleniumDriver

            logger.info("Creating SeleniumDriver (browser=%s)", browser)
            return SeleniumDriver(
                browser=browser,
                headless=headless,
                auto_install=config.get("auto_install", True),
                mobile=config.get("mobile", False),
            )

        else:
            raise ValueError(
                f"Unknown driver_type: {driver_type!r}. "
                "Supported values: 'selenium', 'playwright'."
            )

    @staticmethod
    def _map_browser_to_playwright(browser: str) -> str:
        """Map a generic browser name to a Playwright browser type.

        Args:
            browser: Generic browser name (e.g. "chrome", "firefox", "safari").

        Returns:
            Playwright browser type string ("chromium", "firefox", or "webkit").

        Raises:
            ValueError: If browser name is not recognized.
        """
        browser_lower = browser.lower()
        if browser_lower in _BROWSER_TO_PLAYWRIGHT:
            return _BROWSER_TO_PLAYWRIGHT[browser_lower]
        raise ValueError(
            f"Unknown browser: {browser!r}. "
            f"Supported: {', '.join(sorted(_BROWSER_TO_PLAYWRIGHT.keys()))}"
        )
```

### Key Constraints

- `create()` must be a `@staticmethod` — no instance needed
- Lazy imports of `PlaywrightDriver` and `SeleniumDriver` inside the branches
  so the factory module doesn't require both libraries
- Return an un-started driver — caller is responsible for `await driver.start()`
- Accept both `dict` and `DriverConfig` (Pydantic model) as input
- Map browser names consistently via `_map_browser_to_playwright()`

### References in Codebase

- `sdd/proposals/scrapingplan-playwrightdriver.md` Section 4 — factory design
- `parrot/tools/scraping/drivers/` (TASK-056, TASK-058, TASK-059) — driver classes

---

## Acceptance Criteria

- [ ] `DriverFactory.create()` returns `SeleniumDriver` by default (no config)
- [ ] `DriverFactory.create({"driver_type": "playwright"})` returns `PlaywrightDriver`
- [ ] `DriverFactory.create({"driver_type": "unknown"})` raises `ValueError`
- [ ] `_map_browser_to_playwright` maps all expected browser names correctly
- [ ] `_map_browser_to_playwright("opera")` raises `ValueError`
- [ ] Factory lazily imports driver classes (module loads without both libraries)
- [ ] Returned driver is an `AbstractDriver` instance
- [ ] `DriverFactory` is exported from `parrot.tools.scraping`
- [ ] All tests pass: `pytest tests/tools/scraping/test_driver_factory.py -v`
- [ ] No linting errors: `ruff check parrot/tools/scraping/driver_factory.py`

---

## Test Specification

```python
# tests/tools/scraping/test_driver_factory.py
import pytest
from unittest.mock import patch, MagicMock

from parrot.tools.scraping.driver_factory import DriverFactory
from parrot.tools.scraping.drivers.abstract import AbstractDriver


class TestDriverFactoryCreate:
    @patch("parrot.tools.scraping.driver_factory.SeleniumDriver")
    def test_default_creates_selenium(self, mock_cls):
        mock_cls.return_value = MagicMock(spec=AbstractDriver)
        driver = DriverFactory.create()
        mock_cls.assert_called_once()
        assert isinstance(driver, AbstractDriver)

    @patch("parrot.tools.scraping.driver_factory.PlaywrightDriver")
    @patch("parrot.tools.scraping.driver_factory.PlaywrightConfig")
    def test_playwright_driver_type(self, mock_config, mock_cls):
        mock_cls.return_value = MagicMock(spec=AbstractDriver)
        driver = DriverFactory.create({"driver_type": "playwright"})
        mock_cls.assert_called_once()
        assert isinstance(driver, AbstractDriver)

    def test_unknown_driver_type_raises(self):
        with pytest.raises(ValueError, match="Unknown driver_type"):
            DriverFactory.create({"driver_type": "puppeteer"})


class TestMapBrowserToPlaywright:
    @pytest.mark.parametrize("browser,expected", [
        ("chrome", "chromium"),
        ("chromium", "chromium"),
        ("firefox", "firefox"),
        ("safari", "webkit"),
        ("webkit", "webkit"),
        ("edge", "chromium"),
        ("Chrome", "chromium"),
    ])
    def test_valid_mappings(self, browser, expected):
        assert DriverFactory._map_browser_to_playwright(browser) == expected

    def test_unknown_browser_raises(self):
        with pytest.raises(ValueError, match="Unknown browser"):
            DriverFactory._map_browser_to_playwright("opera")


class TestDriverFactoryWithDict:
    @patch("parrot.tools.scraping.driver_factory.SeleniumDriver")
    def test_dict_config(self, mock_cls):
        mock_cls.return_value = MagicMock(spec=AbstractDriver)
        DriverFactory.create({"browser": "firefox", "headless": False})
        mock_cls.assert_called_once_with(
            browser="firefox", headless=False, auto_install=True, mobile=False
        )


class TestDriverFactoryExports:
    def test_importable_from_package(self):
        from parrot.tools.scraping import DriverFactory as DF
        assert DF is DriverFactory
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scraping-playwrightdriver.spec.md` for full context
2. **Check dependencies** — TASK-056, TASK-058, TASK-059 must be in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-060-driver-factory.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: DriverFactory with `create()` static method and `_map_browser_to_playwright()`
helper. Accepts dict, Pydantic model (via model_dump()), or dataclass config. Lazy
imports of PlaywrightDriver and SeleniumDriver inside create() branches. Exported
from `parrot.tools.scraping`. 20 unit tests covering all branches, browser mappings,
config normalization, error cases, and exports.

**Deviations from spec**: none
