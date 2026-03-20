# TASK-059: SeleniumDriver Refactor

**Feature**: FEAT-015 — PlaywrightDriver
**Spec**: `sdd/specs/scraping-playwrightdriver.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-056
**Assigned-to**: unassigned

---

## Context

> This task implements Module 4 from the spec: wrapping the existing
> `SeleniumSetup` class in a new `SeleniumDriver` that implements
> `AbstractDriver`. This is a refactor-only task — the existing `driver.py`
> (containing `SeleniumSetup`) is NOT modified. Instead, `SeleniumDriver`
> delegates to `SeleniumSetup` internally, adapting its synchronous Selenium
> calls to the async `AbstractDriver` interface via `run_in_executor`.

---

## Scope

- Implement `SeleniumDriver(AbstractDriver)` that:
  - Accepts optional constructor parameters matching `SeleniumSetup` init
  - Delegates to `SeleniumSetup` for all browser operations
  - Wraps all blocking Selenium calls in `asyncio.get_event_loop().run_in_executor()`
  - Implements all abstract methods from `AbstractDriver`:
    - Lifecycle: `start()` → creates `SeleniumSetup` instance, `quit()` → calls `driver.quit()`
    - Navigation: `navigate()`, `go_back()`, `go_forward()`, `reload()`
    - DOM: `click()`, `fill()`, `select_option()`, `hover()`, `press_key()`
    - Extraction: `get_page_source()`, `get_text()`, `get_attribute()`,
      `get_all_texts()`, `screenshot()`
    - Waiting: `wait_for_selector()`, `wait_for_navigation()`, `wait_for_load_state()`
    - Scripts: `execute_script()`, `evaluate()`
    - Property: `current_url`
  - Extended capability methods inherit `NotImplementedError` from base class
    (Selenium does not support HAR, tracing, PDF, interception)
- Lazy Selenium import inside `start()`
- Do **NOT** modify `parrot/tools/scraping/driver.py`

**NOT in scope**: Modifying `driver.py`, PlaywrightDriver (TASK-058),
DriverFactory (TASK-060)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/drivers/selenium_driver.py` | CREATE | `SeleniumDriver` wrapper around `SeleniumSetup` |
| `tests/tools/scraping/test_selenium_driver.py` | CREATE | Unit tests with mocked Selenium |

---

## Implementation Notes

### Pattern to Follow

```python
import asyncio
import logging
from typing import Any, Dict, List, Optional

from .abstract import AbstractDriver


class SeleniumDriver(AbstractDriver):
    """Selenium-based browser automation driver.

    Wraps the existing SeleniumSetup class to implement the AbstractDriver
    interface. All blocking Selenium calls are run via run_in_executor
    to avoid blocking the async event loop.

    Args:
        browser: Browser name ("chrome", "firefox", "edge", "undetected").
        headless: Whether to run in headless mode.
        auto_install: Whether to auto-install the browser driver.
        mobile: Whether to emulate a mobile viewport.
        options: Additional browser-specific options.
    """

    def __init__(
        self,
        browser: str = "chrome",
        headless: bool = True,
        auto_install: bool = True,
        mobile: bool = False,
        options: Optional[Dict[str, Any]] = None,
    ):
        self._browser_name = browser
        self._headless = headless
        self._auto_install = auto_install
        self._mobile = mobile
        self._options = options or {}
        self._setup = None  # SeleniumSetup instance, created in start()
        self._driver = None  # WebDriver instance
        self.logger = logging.getLogger(__name__)

    async def _run(self, func, *args, **kwargs):
        """Run a blocking function in the default executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: func(*args, **kwargs)
        )

    async def start(self) -> None:
        # Lazy import — only require selenium when actually used
        from parrot.tools.scraping.driver import SeleniumSetup

        self._setup = SeleniumSetup(
            browser=self._browser_name,
            headless=self._headless,
            auto_install=self._auto_install,
        )
        self._driver = await self._run(self._setup.get_driver)

    async def quit(self) -> None:
        if self._driver:
            await self._run(self._driver.quit)
            self._driver = None
            self._setup = None

    async def navigate(self, url: str, timeout: int = 30) -> None:
        self._driver.set_page_load_timeout(timeout)
        await self._run(self._driver.get, url)

    @property
    def current_url(self) -> str:
        return self._driver.current_url if self._driver else ""

    # ... remaining abstract methods follow same pattern:
    # wrap self._driver.<method> calls in self._run()
```

### Key Constraints

- **Lazy import**: `from parrot.tools.scraping.driver import SeleniumSetup` must
  happen inside `start()`, NOT at module level
- **run_in_executor**: ALL blocking Selenium calls must go through `_run()` helper
  to avoid blocking the event loop
- **Do NOT modify `driver.py`**: The existing `SeleniumSetup` class is used as-is
- **Extended capabilities**: Inherit the base class `NotImplementedError` defaults —
  do not override them
- **Mock SeleniumSetup in tests**: Use `unittest.mock` to mock `SeleniumSetup` and
  the WebDriver — do NOT require a real browser

### References in Codebase

- `parrot/tools/scraping/driver.py` — existing `SeleniumSetup` class to wrap
- `sdd/proposals/scrapingplan-playwrightdriver.md` Section 9 — SeleniumDriver design
- `parrot/tools/scraping/drivers/abstract.py` (TASK-056) — interface to implement

---

## Acceptance Criteria

- [ ] `SeleniumDriver` implements all abstract methods from `AbstractDriver`
- [ ] `isinstance(SeleniumDriver(), AbstractDriver)` is `True`
- [ ] Lazy Selenium import — module loads without `selenium` installed
- [ ] All blocking calls run through `run_in_executor` (never block the event loop)
- [ ] `parrot/tools/scraping/driver.py` is NOT modified
- [ ] Extended capabilities (`intercept_requests`, `record_har`, etc.) raise
  `NotImplementedError` (inherited from base)
- [ ] All tests pass: `pytest tests/tools/scraping/test_selenium_driver.py -v`
- [ ] No linting errors: `ruff check parrot/tools/scraping/drivers/selenium_driver.py`
- [ ] Import works: `from parrot.tools.scraping.drivers.selenium_driver import SeleniumDriver`

---

## Test Specification

```python
# tests/tools/scraping/test_selenium_driver.py
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from parrot.tools.scraping.drivers.selenium_driver import SeleniumDriver
from parrot.tools.scraping.drivers.abstract import AbstractDriver


class TestSeleniumDriverIsAbstractDriver:
    def test_isinstance(self):
        driver = SeleniumDriver()
        assert isinstance(driver, AbstractDriver)

    def test_default_browser(self):
        driver = SeleniumDriver()
        assert driver._browser_name == "chrome"


class TestSeleniumDriverLifecycle:
    @pytest.mark.asyncio
    @patch("parrot.tools.scraping.drivers.selenium_driver.SeleniumSetup")
    async def test_start_creates_setup(self, mock_setup_cls):
        # SeleniumSetup is imported lazily inside start()
        mock_instance = MagicMock()
        mock_instance.get_driver.return_value = MagicMock()
        mock_setup_cls.return_value = mock_instance

        driver = SeleniumDriver()
        # Patch import path
        with patch(
            "parrot.tools.scraping.drivers.selenium_driver.SeleniumSetup",
            mock_setup_cls,
        ):
            await driver.start()

        assert driver._driver is not None

    @pytest.mark.asyncio
    async def test_quit_clears_state(self):
        driver = SeleniumDriver()
        driver._driver = MagicMock()
        driver._setup = MagicMock()
        await driver.quit()
        assert driver._driver is None
        assert driver._setup is None


class TestSeleniumDriverExtendedCapabilities:
    @pytest.fixture
    def driver(self):
        return SeleniumDriver()

    @pytest.mark.asyncio
    async def test_intercept_requests_raises(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.intercept_requests(lambda r: r)

    @pytest.mark.asyncio
    async def test_record_har_raises(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.record_har("/tmp/test.har")

    @pytest.mark.asyncio
    async def test_save_pdf_raises(self, driver):
        with pytest.raises(NotImplementedError):
            await driver.save_pdf("/tmp/test.pdf")


class TestSeleniumDriverCurrentUrl:
    def test_current_url_empty_when_no_driver(self):
        driver = SeleniumDriver()
        assert driver.current_url == ""

    def test_current_url_from_driver(self):
        driver = SeleniumDriver()
        driver._driver = MagicMock()
        driver._driver.current_url = "https://example.com"
        assert driver.current_url == "https://example.com"


class TestLazyImport:
    def test_module_loads_without_selenium(self):
        from parrot.tools.scraping.drivers.selenium_driver import SeleniumDriver
        assert SeleniumDriver is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scraping-playwrightdriver.spec.md` for full context
2. **Check dependencies** — TASK-056 must be in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-059-selenium-driver.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Full SeleniumDriver implementation wrapping existing SeleniumSetup class.
All 22 abstract methods implemented. Blocking Selenium calls dispatched via
`run_in_executor` using a `_run()` helper with `functools.partial`. Selector
auto-detection (CSS vs XPath) mirrors PlaywrightDriver pattern. Private sync
helpers `_select_by_value`, `_hover_element`, `_press_key_sync` isolate Selenium
imports for testability. 33 unit tests passing with all Selenium calls mocked.
`driver.py` NOT modified.

**Deviations from spec**: Added `_wait_for_element` internal helper to wait for
element presence before DOM interactions (click, fill, get_text, etc.), which is
standard Selenium practice. Extracted `_select_by_value`, `_hover_element`, and
`_press_key_sync` as private blocking methods to make them independently testable
without needing to mock Selenium's internal classes at module level.
