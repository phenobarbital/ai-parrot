# TASK-058: PlaywrightDriver Implementation

**Feature**: FEAT-015 — PlaywrightDriver
**Spec**: `sdd/specs/scraping-playwrightdriver.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: L (4–8h)
**Depends-on**: TASK-056, TASK-057
**Assigned-to**: claude-session

---

## Context

> This task implements Module 3 from the spec: the full `PlaywrightDriver` class
> that implements `AbstractDriver` using the Playwright async API. This is the
> primary deliverable of FEAT-015 — a first-class Playwright browser automation
> driver with feature parity to SeleniumDriver plus Playwright-exclusive
> capabilities (request interception, HAR recording, tracing, PDF export,
> session persistence).

---

## Scope

- Implement `PlaywrightDriver(AbstractDriver)` class that:
  - Accepts a `PlaywrightConfig` in its constructor
  - Implements **all abstract methods** from `AbstractDriver`:
    - Lifecycle: `start()`, `quit()`
    - Navigation: `navigate()`, `go_back()`, `go_forward()`, `reload()`
    - DOM: `click()`, `fill()`, `select_option()`, `hover()`, `press_key()`
    - Extraction: `get_page_source()`, `get_text()`, `get_attribute()`,
      `get_all_texts()`, `screenshot()`
    - Waiting: `wait_for_selector()`, `wait_for_navigation()`, `wait_for_load_state()`
    - Scripts: `execute_script()`, `evaluate()`
    - Property: `current_url`
  - Implements **Playwright-exclusive features** (overriding the NotImplementedError defaults):
    - `intercept_requests(handler)` — route all requests through handler
    - `intercept_by_resource_type(resource_types, action)` — block/modify by type
    - `mock_route(url_pattern, handler)` — mock network responses
    - `record_har(path)` — begin HAR recording
    - `save_pdf(path)` — export page as PDF (chromium-only)
    - `start_tracing(name, screenshots, snapshots)` — begin Playwright trace
    - `stop_tracing(path)` — stop trace and save zip
    - `save_storage_state(path)` — persist cookies/localStorage
    - `new_page()` — create additional page in same context
    - `get_network_responses()` — return captured network responses
  - Internal helpers:
    - `_resolve_selector(selector)` — auto-detect CSS vs XPath
    - `_build_context_kwargs()` — build context creation kwargs from config

**NOT in scope**: SeleniumDriver (TASK-059), DriverFactory (TASK-060),
WebScrapingTool integration (TASK-061)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/drivers/playwright_driver.py` | CREATE | Full `PlaywrightDriver` implementation |
| `tests/tools/scraping/test_playwright_driver.py` | CREATE | Unit tests with mocked Playwright API |

---

## Implementation Notes

### Pattern to Follow

```python
import logging
from typing import Any, Callable, Dict, List, Optional

from .abstract import AbstractDriver
from .playwright_config import PlaywrightConfig


class PlaywrightDriver(AbstractDriver):
    """Playwright-based browser automation driver.

    Implements the full AbstractDriver interface using Playwright's async API,
    plus Playwright-exclusive capabilities (HAR, tracing, PDF, interception).

    Args:
        config: PlaywrightConfig instance with browser/context settings.
    """

    def __init__(self, config: Optional[PlaywrightConfig] = None):
        self.config = config or PlaywrightConfig()
        self.logger = logging.getLogger(__name__)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._responses: List[Dict[str, Any]] = []

    async def start(self) -> None:
        # Lazy import — only require playwright when actually used
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        browser_launcher = getattr(self._playwright, self.config.browser_type)
        self._browser = await browser_launcher.launch(
            headless=self.config.headless,
            slow_mo=self.config.slow_mo,
        )
        context_kwargs = self._build_context_kwargs()
        self._context = await self._browser.new_context(**context_kwargs)
        self._page = await self._context.new_page()

    def _build_context_kwargs(self) -> Dict[str, Any]:
        """Build keyword arguments for browser.new_context() from config."""
        kwargs: Dict[str, Any] = {}
        if self.config.viewport:
            kwargs["viewport"] = self.config.viewport
        if self.config.locale:
            kwargs["locale"] = self.config.locale
        if self.config.timezone:
            kwargs["timezone_id"] = self.config.timezone
        if self.config.geolocation:
            kwargs["geolocation"] = self.config.geolocation
        if self.config.permissions:
            kwargs["permissions"] = self.config.permissions
        if self.config.ignore_https_errors:
            kwargs["ignore_https_errors"] = True
        if self.config.extra_http_headers:
            kwargs["extra_http_headers"] = self.config.extra_http_headers
        if self.config.http_credentials:
            kwargs["http_credentials"] = self.config.http_credentials
        if self.config.record_video_dir:
            kwargs["record_video_dir"] = self.config.record_video_dir
        if self.config.record_har_path:
            kwargs["record_har_path"] = self.config.record_har_path
        if self.config.storage_state:
            kwargs["storage_state"] = self.config.storage_state
        if self.config.proxy:
            kwargs["proxy"] = self.config.proxy
        return kwargs

    def _resolve_selector(self, selector: str) -> str:
        """Auto-detect and return appropriate selector.

        If selector starts with '/' or './' treat as XPath,
        otherwise treat as CSS selector.
        """
        if selector.startswith(("/", "./")):
            return f"xpath={selector}"
        return selector

    async def navigate(self, url: str, timeout: int = 30) -> None:
        await self._page.goto(url, timeout=timeout * 1000)

    # ... remaining methods follow same pattern:
    # convert seconds to milliseconds for Playwright API calls
```

### Key Constraints

- **Lazy import**: `from playwright.async_api import async_playwright` must happen
  inside `start()`, NOT at module level — Playwright is an optional dependency
- **Seconds to milliseconds**: All `timeout` parameters in AbstractDriver are in
  seconds; Playwright API uses milliseconds — multiply by 1000 at the boundary
- **`save_pdf` chromium-only**: Must check `self.config.browser_type == "chromium"`
  and raise `ValueError` if called with Firefox/WebKit
- **`_resolve_selector`**: XPath selectors start with `/` or `./` — prefix with
  `xpath=` for Playwright; CSS selectors are used as-is
- **Mock Playwright in tests**: Use `unittest.mock.AsyncMock` to mock the Playwright
  API — do NOT require a real browser in unit tests

### References in Codebase

- `sdd/proposals/scrapingplan-playwrightdriver.md` Sections 3, 6, 7, 8 — full implementation details
- `sdd/specs/scraping-playwrightdriver.spec.md` §2 — architectural design
- `parrot/tools/scraping/drivers/abstract.py` (TASK-056) — interface to implement
- `parrot/tools/scraping/drivers/playwright_config.py` (TASK-057) — config dataclass

---

## Acceptance Criteria

- [ ] `PlaywrightDriver` implements all abstract methods from `AbstractDriver`
- [ ] `isinstance(PlaywrightDriver(), AbstractDriver)` is `True`
- [ ] Lazy Playwright import — module loads without `playwright` installed
- [ ] All timeouts converted from seconds to milliseconds at the Playwright boundary
- [ ] `save_pdf` raises `ValueError` for non-chromium browser types
- [ ] `_resolve_selector` correctly distinguishes CSS from XPath selectors
- [ ] `_build_context_kwargs` maps all config fields to Playwright context arguments
- [ ] Extended capabilities (`intercept_requests`, `record_har`, `save_pdf`,
  `start_tracing`, `stop_tracing`, `mock_route`) are implemented (not raising
  `NotImplementedError`)
- [ ] All tests pass: `pytest tests/tools/scraping/test_playwright_driver.py -v`
- [ ] No linting errors: `ruff check parrot/tools/scraping/drivers/playwright_driver.py`
- [ ] Import works: `from parrot.tools.scraping.drivers.playwright_driver import PlaywrightDriver`

---

## Test Specification

```python
# tests/tools/scraping/test_playwright_driver.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.tools.scraping.drivers.playwright_driver import PlaywrightDriver
from parrot.tools.scraping.drivers.playwright_config import PlaywrightConfig
from parrot.tools.scraping.drivers.abstract import AbstractDriver


class TestPlaywrightDriverIsAbstractDriver:
    def test_isinstance(self):
        driver = PlaywrightDriver()
        assert isinstance(driver, AbstractDriver)

    def test_default_config(self):
        driver = PlaywrightDriver()
        assert driver.config.browser_type == "chromium"
        assert driver.config.headless is True


class TestResolveSelector:
    def test_css_selector(self):
        driver = PlaywrightDriver()
        assert driver._resolve_selector("div.class") == "div.class"

    def test_xpath_selector_slash(self):
        driver = PlaywrightDriver()
        assert driver._resolve_selector("//div[@id='main']") == "xpath=//div[@id='main']"

    def test_xpath_selector_dot_slash(self):
        driver = PlaywrightDriver()
        assert driver._resolve_selector("./div") == "xpath=./div"


class TestBuildContextKwargs:
    def test_empty_config(self):
        driver = PlaywrightDriver(PlaywrightConfig())
        kwargs = driver._build_context_kwargs()
        assert kwargs == {}

    def test_viewport_included(self):
        config = PlaywrightConfig(viewport={"width": 1280, "height": 720})
        driver = PlaywrightDriver(config)
        kwargs = driver._build_context_kwargs()
        assert kwargs["viewport"] == {"width": 1280, "height": 720}

    def test_locale_and_timezone(self):
        config = PlaywrightConfig(locale="en-US", timezone="America/New_York")
        driver = PlaywrightDriver(config)
        kwargs = driver._build_context_kwargs()
        assert kwargs["locale"] == "en-US"
        assert kwargs["timezone_id"] == "America/New_York"

    def test_storage_state(self):
        config = PlaywrightConfig(storage_state="/tmp/state.json")
        driver = PlaywrightDriver(config)
        kwargs = driver._build_context_kwargs()
        assert kwargs["storage_state"] == "/tmp/state.json"


class TestSavePdfChromiumOnly:
    @pytest.mark.asyncio
    async def test_raises_for_firefox(self):
        config = PlaywrightConfig(browser_type="firefox")
        driver = PlaywrightDriver(config)
        driver._page = AsyncMock()
        with pytest.raises(ValueError, match="chromium"):
            await driver.save_pdf("/tmp/out.pdf")


class TestNavigateTimeoutConversion:
    @pytest.mark.asyncio
    async def test_timeout_converted_to_ms(self):
        driver = PlaywrightDriver()
        driver._page = AsyncMock()
        await driver.navigate("https://example.com", timeout=5)
        driver._page.goto.assert_called_once_with(
            "https://example.com", timeout=5000
        )


class TestLazyImport:
    def test_module_loads_without_playwright(self):
        """PlaywrightDriver module should load even if playwright is not installed."""
        # This test passes by virtue of being able to import the module
        from parrot.tools.scraping.drivers.playwright_driver import PlaywrightDriver
        assert PlaywrightDriver is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scraping-playwrightdriver.spec.md` for full context
2. **Check dependencies** — TASK-056 and TASK-057 must be in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-058-playwright-driver.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Full PlaywrightDriver implementation with all 22 abstract methods + 10
Playwright-exclusive features (intercept_requests, intercept_by_resource_type,
mock_route, record_har, save_pdf, start_tracing, stop_tracing, save_storage_state,
new_page, get_network_responses). 56 unit tests covering all methods with mocked
Playwright API. Key patterns: lazy import of playwright in start(), seconds-to-ms
timeout conversion, XPath auto-detection via _resolve_selector(), chromium-only
guard on save_pdf().

**Deviations from spec**: Added `intercept_by_resource_type`, `save_storage_state`,
`new_page`, and `get_network_responses` as additional Playwright-exclusive methods
beyond the spec's minimum list. Also added `set_default_timeout` on context creation
and proxy support in launch kwargs.
