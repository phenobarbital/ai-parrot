# Feature Specification: PlaywrightDriver (First-Class Playwright Support)

**Feature ID**: FEAT-015
**Date**: 2026-02-25
**Author**: claude-session
**Status**: approved
**Target version**: 1.0.0

---

## 1. Motivation & Business Requirements

> Replace the monolithic Selenium-only `SeleniumSetup` class with a proper driver
> abstraction layer, enabling first-class Playwright support alongside the existing
> Selenium backend.

### Problem Statement

The current `parrot/tools/scraping/driver.py` contains a monolithic `SeleniumSetup`
class tightly coupled to Selenium WebDriver. There is no abstract driver interface,
making it impossible to add alternative browser automation backends without duplicating
logic or introducing brittle conditionals. Playwright offers significant advantages
for modern web scraping — native async support, built-in auto-wait, request interception,
HAR recording, tracing, PDF export, and session persistence — none of which are available
through the current Selenium-only architecture.

### Goals
- Define an `AbstractDriver` ABC that both Selenium and Playwright drivers implement
- Implement a full-featured `PlaywrightDriver` with parity to SeleniumDriver plus
  Playwright-exclusive capabilities (HAR, tracing, PDF, request interception, session reuse)
- Create a `DriverFactory` that selects the correct driver based on configuration
- Refactor `SeleniumSetup` into a `SeleniumDriver` that implements `AbstractDriver`
- Wire `DriverFactory` into `WebScrapingTool` replacing direct `SeleniumSetup` usage
- Zero breaking changes to the existing `WebScrapingTool` public API

### Non-Goals (explicitly out of scope)
- Removing Selenium support — both drivers coexist
- Implementing browser binary auto-installation (Playwright's `playwright install` is
  the user's responsibility)
- Stealth/anti-detection plugins for Playwright (can be added later)
- Modifying the step-execution engine beyond swapping driver method calls

---

## 2. Architectural Design

### Overview

Introduce a `drivers/` subpackage under `parrot/tools/scraping/` containing an abstract
base class and two concrete implementations. A `DriverFactory` handles instantiation.
`WebScrapingTool` uses the factory instead of directly creating `SeleniumSetup`.

### Component Diagram
```
WebScrapingTool
      │
      ▼
DriverFactory.create(config)
      │
      ├──→ SeleniumDriver(AbstractDriver)   [refactored from driver.py]
      │
      └──→ PlaywrightDriver(AbstractDriver)  [NEW]
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `SeleniumSetup` (driver.py) | refactored into | `SeleniumDriver` wraps existing logic |
| `WebScrapingTool` (tool.py) | uses | Calls `DriverFactory.create()` instead of `SeleniumSetup()` |
| `ScrapingPlan` (plan.py) | unchanged | Plans are driver-agnostic |
| `PlanRegistry` (registry.py) | unchanged | No driver dependency |

### Data Models

```python
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Union

@dataclass
class PlaywrightConfig:
    browser_type: Literal["chromium", "firefox", "webkit"] = "chromium"
    headless: bool = True
    slow_mo: int = 0
    timeout: int = 30_000
    viewport: Optional[Dict] = None
    locale: str = "en-US"
    timezone: Optional[str] = None
    geolocation: Optional[Dict] = None
    permissions: List[str] = field(default_factory=list)
    mobile: bool = False
    device_name: Optional[str] = None
    proxy: Optional[Dict] = None
    ignore_https_errors: bool = False
    extra_http_headers: Dict[str, str] = field(default_factory=dict)
    http_credentials: Optional[Dict] = None
    record_video_dir: Optional[str] = None
    record_har_path: Optional[str] = None
    storage_state: Optional[Union[str, Dict]] = None
```

### New Public Interfaces

```python
from abc import ABC, abstractmethod

class AbstractDriver(ABC):
    """Unified interface for browser automation drivers."""
    async def start(self) -> None: ...
    async def quit(self) -> None: ...
    async def navigate(self, url: str, timeout: int = 30) -> None: ...
    async def click(self, selector: str, selector_type: str = "css") -> None: ...
    async def fill(self, selector: str, value: str, selector_type: str = "css") -> None: ...
    async def get_text(self, selector: str, selector_type: str = "css", multiple: bool = False) -> Any: ...
    async def get_html(self, selector: Optional[str] = None) -> str: ...
    async def screenshot(self, filepath: str, full_page: bool = False) -> str: ...
    async def evaluate(self, script: str) -> Any: ...
    # ... plus waiting, cookies, scrolling, hover, drag_and_drop, etc.
    # Extended (Playwright-only, raise NotImplementedError on Selenium):
    async def intercept_requests(self, handler: Any) -> None: ...
    async def record_har(self, path: str) -> None: ...
    async def save_pdf(self, filepath: str) -> str: ...
    async def start_tracing(self, screenshots: bool = True, snapshots: bool = True) -> None: ...
    async def stop_tracing(self, output_path: str) -> None: ...

class PlaywrightDriver(AbstractDriver):
    """First-class Playwright implementation."""
    def __init__(self, config: Optional[PlaywrightConfig] = None, **kwargs): ...

class SeleniumDriver(AbstractDriver):
    """Thin wrapper around existing SeleniumSetup logic."""
    def __init__(self, config: Any): ...

class DriverFactory:
    @staticmethod
    async def create(config: "DriverConfig") -> AbstractDriver: ...
```

---

## 3. Module Breakdown

### Module 1: AbstractDriver Interface
- **Path**: `parrot/tools/scraping/drivers/abstract.py`
- **Responsibility**: Define the `AbstractDriver` ABC with all lifecycle, navigation,
  DOM interaction, extraction, waiting, media, and extended capability methods
- **Depends on**: nothing (pure interface)

### Module 2: PlaywrightConfig
- **Path**: `parrot/tools/scraping/drivers/playwright_config.py`
- **Responsibility**: `PlaywrightConfig` dataclass with all Playwright-specific
  configuration (browser type, viewport, locale, proxy, mobile emulation, recording,
  storage state)
- **Depends on**: nothing

### Module 3: PlaywrightDriver
- **Path**: `parrot/tools/scraping/drivers/playwright_driver.py`
- **Responsibility**: Full `PlaywrightDriver` implementation — lifecycle management
  (`async_playwright` context), navigation, DOM interaction via locators, extraction,
  waiting, screenshots, script evaluation, plus Playwright-exclusive features: request
  interception, route mocking, HAR recording, PDF export, tracing, storage state
  persistence, multi-tab support, network response capture
- **Depends on**: Module 1, Module 2

### Module 4: SeleniumDriver Refactor
- **Path**: `parrot/tools/scraping/drivers/selenium_driver.py`
- **Responsibility**: Wrap existing `SeleniumSetup` logic into a class that implements
  `AbstractDriver`. Each abstract method delegates to the existing Selenium API calls
  (via `run_in_executor` for blocking ops). Extended capability methods raise
  `NotImplementedError`.
- **Depends on**: Module 1, existing `driver.py`

### Module 5: DriverFactory
- **Path**: `parrot/tools/scraping/driver_factory.py`
- **Responsibility**: `DriverFactory.create(config)` that selects and instantiates the
  correct driver based on `config.driver_type`. Includes `_map_browser_to_playwright()`
  helper for browser name normalization.
- **Depends on**: Module 1, Module 3, Module 4

### Module 6: WebScrapingTool Integration
- **Path**: `parrot/tools/scraping/tool.py` (MODIFY)
- **Responsibility**: Replace direct `SeleniumSetup` usage with `DriverFactory.create()`.
  Update step-execution to call `AbstractDriver` methods. Update `__init__.py` exports.
- **Depends on**: Module 5

### Module 7: Tests
- **Path**: `tests/tools/scraping/test_abstract_driver.py`, `tests/tools/scraping/test_playwright_driver.py`, `tests/tools/scraping/test_selenium_driver.py`, `tests/tools/scraping/test_driver_factory.py`
- **Responsibility**: Unit tests for all modules. PlaywrightDriver tests mock the
  Playwright API (no real browser). SeleniumDriver tests mock WebDriver. DriverFactory
  tests verify correct dispatch.
- **Depends on**: Module 1–6

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_abstract_driver_cannot_instantiate` | Module 1 | ABC prevents direct instantiation |
| `test_extended_methods_raise_not_implemented` | Module 1 | Default extended methods raise NotImplementedError |
| `test_playwright_config_defaults` | Module 2 | Default values for all config fields |
| `test_playwright_config_custom` | Module 2 | Custom config overrides |
| `test_playwright_lifecycle` | Module 3 | start() → navigate() → quit() |
| `test_playwright_selector_resolution` | Module 3 | CSS, XPath, text, role, id selectors |
| `test_playwright_dom_interaction` | Module 3 | click, fill, select_option, press_key, scroll, hover |
| `test_playwright_extraction` | Module 3 | get_text, get_html, get_attribute, get_cookies |
| `test_playwright_waiting` | Module 3 | wait_for_selector, wait_for_url, wait_for_load_state |
| `test_playwright_screenshot` | Module 3 | screenshot with full_page option |
| `test_playwright_intercept_requests` | Module 3 | Request interception handler registration |
| `test_playwright_intercept_by_resource_type` | Module 3 | Block specific resource types |
| `test_playwright_mock_route` | Module 3 | Route mocking with custom response |
| `test_playwright_pdf_chromium_only` | Module 3 | PDF export on chromium, NotImplementedError on others |
| `test_playwright_tracing` | Module 3 | start_tracing + stop_tracing lifecycle |
| `test_playwright_storage_state` | Module 3 | save_storage_state round-trip |
| `test_playwright_network_responses` | Module 3 | get_network_responses captures matching responses |
| `test_selenium_driver_implements_interface` | Module 4 | SeleniumDriver satisfies AbstractDriver |
| `test_selenium_extended_raises` | Module 4 | Extended methods raise NotImplementedError |
| `test_factory_creates_playwright` | Module 5 | driver_type="playwright" → PlaywrightDriver |
| `test_factory_creates_selenium` | Module 5 | driver_type="selenium" → SeleniumDriver |
| `test_factory_browser_mapping` | Module 5 | Browser name normalization (chrome→chromium, etc.) |
| `test_factory_unknown_browser_defaults` | Module 5 | Unknown browser falls back to chromium |

### Integration Tests

| Test | Description |
|---|---|
| `test_tool_uses_factory` | WebScrapingTool creates driver via DriverFactory |
| `test_tool_selenium_backward_compat` | Existing config still creates SeleniumDriver |
| `test_driver_swap_transparent` | Same scraping plan works with both drivers |

### Test Data / Fixtures

```python
@pytest.fixture
def playwright_config():
    return PlaywrightConfig(browser_type="chromium", headless=True)

@pytest.fixture
def mock_playwright():
    """Mock playwright.async_api module for unit tests."""
    ...

@pytest.fixture
def mock_page():
    """Mock Playwright Page with locator support."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `AbstractDriver` ABC defines all required methods (lifecycle, navigation, DOM, extraction, waiting, media, script, extended)
- [ ] `PlaywrightDriver` implements all `AbstractDriver` methods plus Playwright-exclusive features
- [ ] `SeleniumDriver` wraps existing `SeleniumSetup` and implements `AbstractDriver`
- [ ] `DriverFactory.create()` returns correct driver type based on config
- [ ] `WebScrapingTool` uses `DriverFactory` instead of direct `SeleniumSetup`
- [ ] All unit tests pass: `pytest tests/tools/scraping/test_abstract_driver.py tests/tools/scraping/test_playwright_driver.py tests/tools/scraping/test_driver_factory.py -v`
- [ ] No breaking changes to existing `WebScrapingTool` public API
- [ ] `PlaywrightConfig` dataclass covers all configuration options from the proposal
- [ ] Extended capabilities (HAR, tracing, PDF, interception) work on PlaywrightDriver
- [ ] Extended capabilities raise `NotImplementedError` on SeleniumDriver
- [ ] Exports updated in `parrot/tools/scraping/__init__.py`

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Use `AbstractDriver` as a proper ABC (from `abc` module) — same pattern as `AbstractClient`
- Async-first: all driver methods are `async def`
- `PlaywrightDriver` manages the `async_playwright()` context manager across its lifecycle
- `SeleniumDriver` uses `asyncio.get_event_loop().run_in_executor()` to wrap blocking Selenium calls
- Pydantic models or dataclasses for all configuration
- Comprehensive logging with `self.logger`

### Selector Resolution
PlaywrightDriver must translate AI-Parrot's `selector_type` convention:
- `css` → used as-is (Playwright default)
- `xpath` → `xpath=<selector>`
- `text` → `text=<selector>`
- `role` → `role=<selector>`
- `id` → `#<selector>`

### Known Risks / Gotchas
- **Playwright installation**: Requires separate `playwright install` to download browser
  binaries. Tests must mock the Playwright API, not require real browsers.
- **SeleniumSetup complexity**: The existing `driver.py` is large (~600+ lines) with
  many browser-specific branches. The `SeleniumDriver` refactor should be a thin wrapper,
  not a rewrite — delegate to the existing class internally.
- **Async vs sync gap**: Selenium is synchronous; `SeleniumDriver` must use `run_in_executor`
  for all blocking calls to maintain the async interface contract.
- **Backward compatibility**: Existing code referencing `SeleniumSetup` directly must
  continue to work. Keep `driver.py` and its `SeleniumSetup` class unchanged; `SeleniumDriver`
  wraps it.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `playwright` | `>=1.40` | Async browser automation API |

---

## 7. Open Questions

- [x] Should `SeleniumSetup` be replaced or wrapped? — **Resolved: Wrap it.** Keep `driver.py`
  unchanged. `SeleniumDriver` delegates to `SeleniumSetup` internally.
- [x] Auto-save plans: should every LLM-generated plan be saved? — **Resolved in FEAT-012**
- [ ] Should `DriverFactory` support a plugin mechanism for third-party drivers? — *Deferred to future spec*
- [ ] Should `PlaywrightConfig` be a Pydantic model or dataclass? — *Recommend dataclass for simplicity since it's internal config, not serialized*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-25 | claude-session | Initial draft from proposal `sdd/proposals/scrapingplan-playwrightdriver.md` |
