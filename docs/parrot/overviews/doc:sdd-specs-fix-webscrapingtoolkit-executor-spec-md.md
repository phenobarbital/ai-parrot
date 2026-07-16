---
type: Wiki Overview
title: 'Feature Specification: fix-webscrapingtoolkit-executor'
id: doc:sdd-specs-fix-webscrapingtoolkit-executor-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'plan execution directly against a raw **Selenium `WebDriver`**:'
relates_to:
- concept: mod:parrot_tools.scraping.driver
  rel: mentions
- concept: mod:parrot_tools.scraping.driver_context
  rel: mentions
- concept: mod:parrot_tools.scraping.drivers
  rel: mentions
- concept: mod:parrot_tools.scraping.drivers.abstract
  rel: mentions
- concept: mod:parrot_tools.scraping.drivers.playwright_config
  rel: mentions
- concept: mod:parrot_tools.scraping.drivers.playwright_driver
  rel: mentions
- concept: mod:parrot_tools.scraping.drivers.selenium_driver
  rel: mentions
- concept: mod:parrot_tools.scraping.models
  rel: mentions
- concept: mod:parrot_tools.scraping.plan
  rel: mentions
- concept: mod:parrot_tools.scraping.toolkit_models
  rel: mentions
---

# Feature Specification: fix-webscrapingtoolkit-executor

**Feature ID**: FEAT-104
**Date**: 2026-04-17
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

`packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` drives the scraping
plan execution directly against a raw **Selenium `WebDriver`**:

- `driver.get(url)`, `driver.refresh()`, `driver.back()`, `driver.save_screenshot(path)`
- `driver.page_source`, `driver.current_url`
- `driver.execute_script(script, *args)` (sync)
- `driver.switch_to.active_element.send_keys(...)`
- `WebDriverWait(...).until(EC.presence_of_element_located(...))`
- `Select(element).select_by_value(...)`
- `driver.find_element(By.X, ...)` indirectly via `EC.element_to_be_clickable`

After FEAT-? (see `drivers/abstract.py`) a unified `AbstractDriver` contract exists
and both `SeleniumDriver` and `PlaywrightDriver` fully implement it. The
`DriverRegistry` now exposes `"selenium"` and `"playwright"` factories
(`packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py:84-169`). However,
the **executor is still tied to Selenium's API** and to a **raw WebDriver** — not the
`AbstractDriver` wrapper — so `driver_context()` currently must yield a raw Selenium
driver to keep existing behavior. A Playwright driver fed through the same pipeline
raises `AttributeError` on the first step (`driver.get`, `driver.page_source`, …).

The same Selenium-style coupling exists in
`packages/ai-parrot-tools/src/parrot_tools/scraping/page_snapshot.py:483-523`
(`snapshot_from_driver`), which reads `driver.page_source` / `driver.current_url` /
`driver.get(url)` through `run_in_executor`.

### Goals

- **G1** — `execute_plan_steps()` runs identically against a `SeleniumDriver` and a
  `PlaywrightDriver` with **no call-site changes**. Every action handler speaks only
  to the `AbstractDriver` interface.
- **G2** — `snapshot_from_driver()` runs against any `AbstractDriver` (no Selenium
  attribute assumptions).
- **G3** — `DriverRegistry` factories return an **`AbstractDriver`** consistently
  (today `"selenium"` returns a raw `WebDriver`, `"playwright"` returns a
  `PlaywrightDriver`).
- **G4** — `WebScrapingToolkit.scrape()` / `crawl()` work with either backend
  based solely on `DriverConfig.driver_type` — the exact guarantee the README
  and docstrings already imply.
- **G5** — Existing Selenium-backed test suites continue to pass. A new parametric
  test proves parity Selenium ↔ Playwright on the same plan (offline harness).

### Non-Goals (explicitly out of scope)

- Rewriting `WebScrapingTool` (the legacy non-toolkit entry point at
  `scraping/tool.py`) — that class still has a direct Selenium dependency by
  design and is a deprecation target.
- Adding new scraping action types or changing the `BrowserAction` model hierarchy.
- Adding Playwright-exclusive actions (tracing, HAR, PDF) to the plan format.
- Changing `SeleniumSetup` internals (`scraping/driver.py`).
- Changing the `ScrapingPlan` / `ScrapingStep` / `ScrapingSelector` pydantic models.

---

## 2. Architectural Design

### Overview

Treat the `AbstractDriver` surface as the **only** API the executor and snapshot
helpers may call. Concentrate the Selenium-specific knowledge (WebDriverWait,
`Select`, `By`, `Keys`) inside `SeleniumDriver` — where it already lives — and
rewrite the executor in terms of the abstract methods.

The driver_context/Registry must hand out an `AbstractDriver`, not a raw underlying
driver, so downstream code never branches on backend type.

### Component Diagram

```
DriverConfig
     │
     ▼
DriverRegistry.get(driver_type)
     │
     ├── "selenium"  ──► _SeleniumSetupAdapter.get_driver() ──► SeleniumDriver (AbstractDriver)
     └── "playwright"──► _PlaywrightSetup.get_driver()      ──► PlaywrightDriver (AbstractDriver)
                                                                     │
                                                                     ▼
                                               driver_context(config) yields AbstractDriver
                                                                     │
                                    ┌────────────────────────────────┼────────────────────────────────┐
                                    ▼                                ▼                                ▼
                           execute_plan_steps(driver)     snapshot_from_driver(driver)      WebScrapingToolkit (unchanged API)
                                    │
                          All step/action handlers call
                          ONLY AbstractDriver methods
                          (navigate, click, fill, …)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractDriver` | consumer | Executor and snapshot helpers consume only this surface |
| `SeleniumDriver` | reused | Already implements the full contract; used via registry adapter |
| `PlaywrightDriver` | reused | Same — driven through the existing `_PlaywrightSetup` |
| `DriverRegistry` | modified | `"selenium"` factory now returns an adapter whose `get_driver()` yields a started `SeleniumDriver`, not a raw `WebDriver` |
| `driver_context` | unchanged contract | Still yields "a driver"; now that driver is guaranteed to be `AbstractDriver` |
| `WebScrapingToolkit._session_driver` | typing only | Still holds the yielded object; semantics change to `AbstractDriver` |
| `execute_plan_steps` | rewritten internals | Public signature preserved |
| `snapshot_from_driver` | rewritten internals | Public signature preserved |

### Data Models

No new Pydantic models. The executor's action dispatch dictionary is internal.

### New Public Interfaces

None. Everything is internal rewiring. The **signatures** of the following stay
identical:

```python
async def execute_plan_steps(
    driver: AbstractDriver,   # was: Any (effectively Selenium WebDriver)
    plan: Optional[ScrapingPlan] = None,
    steps: Optional[List[Dict[str, Any]]] = None,
    selectors: Optional[List[Dict[str, Any]]] = None,
    config: Optional[DriverConfig] = None,
    base_url: Optional[str] = None,
) -> ScrapingResult: ...

async def snapshot_from_driver(
    driver: AbstractDriver,   # was: Any
    url: Optional[str] = None,
    *,
    settle_seconds: float = 1.0,
) -> Optional[PageSnapshot]: ...
```

---

## 3. Module Breakdown

### Module 1: `scraping/executor.py` (rewrite internals)

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`
- **Responsibility**: Replace every Selenium-specific call inside `_dispatch_step`
  and its action handlers (`_action_navigate`, `_action_wait`, `_action_click`,
  `_action_fill`, `_action_scroll`, `_action_evaluate`, `_action_refresh`,
  `_action_back`, `_action_extract`, `_action_screenshot`, `_action_press_key`,
  `_action_select`) with the corresponding `AbstractDriver` method. Also update
  `_get_current_url` and `_get_page_source` to `await driver.current_url` /
  `await driver.get_page_source()`.
- **Depends on**: `AbstractDriver` contract, `ScrapingStep`/`ScrapingSelector`
  models, `BeautifulSoup`.

**Mapping table (executor → AbstractDriver):**

| Current Selenium call | Replacement |
|---|---|
| `driver.get(url)` | `await driver.navigate(url)` |
| `driver.page_source` | `await driver.get_page_source()` |
| `driver.current_url` (sync property) | `driver.current_url` (still a property — both drivers expose it) |
| `driver.execute_script(script, *args)` | `await driver.execute_script(script, *args)` |
| `driver.refresh()` | `await driver.reload()` |
| `driver.back()` | `await driver.go_back()` |
| `driver.save_screenshot(path)` | `await driver.screenshot(path)` |
| `driver.switch_to.active_element.send_keys(key)` | `await driver.press_key(key)` |
| `WebDriverWait + EC.presence_of_element_located` | `await driver.wait_for_selector(selector, timeout, state="attached")` |
| `WebDriverWait + EC.url_contains` | `await _wait_until(lambda: substring in driver.current_url, timeout)` (new module-private helper) |
| `WebDriverWait + EC.title_contains` | `await _wait_until(lambda: substring in await driver.evaluate("document.title"), timeout)` |
| `wait.until(EC.element_to_be_clickable).click()` | `await driver.click(selector, timeout)` (both drivers handle scroll-into-view internally; confirm for Selenium in Task 2) |
| `element.clear(); element.send_keys(value)` | `await driver.fill(selector, value, timeout)` |
| `Select(element).select_by_value(v)` | `await driver.select_option(selector, v, timeout)` |
| `Select(element).select_by_visible_text(t)` / `select_by_index(i)` | **Extension point** — handle in Task 2 |

### Module 2: `drivers/abstract.py` + `drivers/selenium_driver.py` + `drivers/playwright_driver.py` (minor extensions)

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py`
- **Responsibility**: Fill the small gaps the executor currently relies on that
  have no 1:1 AbstractDriver method:
  - `select_option(selector, value, *, by="value", timeout=10)` — extend the
    existing signature to accept `by: Literal["value", "text", "index"]`.
    Default preserves today's behavior.
  - Ensure `SeleniumDriver.click()` performs the JS `scrollIntoView` fallback
    on `ElementClickInterceptedException` (parity with the current executor's
    `arguments[0].scrollIntoView({block:'center'}); arguments[0].click();`
    branch in `_action_click`).
- **Depends on**: `selenium.webdriver.support.ui.Select`, Playwright
  `locator.select_option(value=..., label=..., index=...)`.

### Module 3: `scraping/page_snapshot.py` (rewrite `snapshot_from_driver`)

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/page_snapshot.py`
- **Responsibility**: Rewrite `snapshot_from_driver` (lines 483-523) against
  `AbstractDriver`: `await driver.navigate(url)` / `await driver.get_page_source()`,
  removing `run_in_executor`. Keep `settle_seconds` semantics.
- **Depends on**: `AbstractDriver`.

### Module 4: `scraping/driver_context.py` (registry wrapper for Selenium)

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py`
- **Responsibility**: Replace `_create_selenium_setup` so its `get_driver()`
  returns a **started `SeleniumDriver`** (an `AbstractDriver`) instead of a raw
  `selenium.webdriver.WebDriver`. Introduce a `_SeleniumSetupAdapter` class
  mirroring `_PlaywrightSetup`. Update `_quit_driver` docstring — it already
  handles both sync and async `quit()`, so no functional change.
- **Depends on**: `SeleniumDriver`, `SeleniumSetup`.

### Module 5: `scraping/toolkit.py` (typing + lifecycle)

- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py`
- **Responsibility**: `_session_driver: Optional[AbstractDriver]` typing update.
  Call sites in `scrape()` / `crawl()` pass the driver straight to
  `execute_plan_steps` and `snapshot_from_driver` — already covered by the new
  signatures. Verify `start()` (line 146) and `stop()` (line 160) still work —
  both already rely on `get_driver()` + `_quit_driver()` abstractions.
- **Depends on**: modules 1, 3, 4.

### Module 6: Tests

- **Paths**:
  - `packages/ai-parrot-tools/tests/scraping/test_executor.py` (update mock driver)
  - `packages/ai-parrot-tools/tests/scraping/test_toolkit.py` (update mock driver)
  - `tests/tools/scraping/test_driver_context.py` (expectation: selenium factory yields `AbstractDriver`)
  - **NEW** `packages/ai-parrot-tools/tests/scraping/test_executor_driver_parity.py`
    — executes the same trivial plan against a mock `AbstractDriver` subclass
    and verifies the driver method-call sequence is identical regardless of
    which concrete backend was registered under a given driver_type alias.
- **Responsibility**: Replace `MagicMock()`-based Selenium-style fixtures with
  `AsyncMock`-backed `AbstractDriver` fakes.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_navigate_calls_driver_navigate` | Module 1 | `_action_navigate` awaits `driver.navigate(url)` |
| `test_wait_selector_uses_wait_for_selector` | Module 1 | `_action_wait(condition_type="selector")` delegates to `driver.wait_for_selector` |
| `test_wait_url_contains_polls_current_url` | Module 1 | Polls `driver.current_url` until substring matches or timeout |
| `test_wait_title_contains_polls_evaluate` | Module 1 | Polls `driver.evaluate("document.title")` |
| `test_click_uses_driver_click` | Module 1 | `_action_click` awaits `driver.click(selector, timeout)` |
| `test_fill_uses_driver_fill` | Module 1 | `_action_fill` awaits `driver.fill(selector, value, timeout)` |
| `test_scroll_uses_execute_script` | Module 1 | `_action_scroll` awaits `driver.execute_script(...)` |
| `test_evaluate_uses_execute_script` | Module 1 | `_action_evaluate` awaits `driver.execute_script(script)` |
| `test_refresh_uses_reload` | Module 1 | `_action_refresh` awaits `driver.reload()` (or `execute_script` for `hard`) |
| `test_back_uses_go_back` | Module 1 | `_action_back` awaits `driver.go_back()` N times |
| `test_extract_reads_get_page_source` | Module 1 | `_action_extract` awaits `driver.get_page_source()` |
| `test_screenshot_uses_driver_screenshot` | Module 1 | `_action_screenshot` awaits `driver.screenshot(path)` |
| `test_press_key_uses_driver_press_key` | Module 1 | `_action_press_key` awaits `driver.press_key(key)` for each key |
| `test_select_uses_select_option_by_value` | Module 1 | `_action_select` by=value uses `driver.select_option(..., by="value")` |
| `test_select_by_text_and_index` | Module 2 | Extended `select_option` handles `by="text"` and `by="index"` in both drivers |
| `test_selenium_click_scrolls_into_view_on_interception` | Module 2 | SeleniumDriver.click retries with `scrollIntoView` JS on `ElementClickInterceptedException` |
| `test_get_current_url_and_page_source_awaited` | Module 1 | `_get_current_url`/`_get_page_source` use awaited AbstractDriver calls |
| `test_snapshot_from_driver_uses_abstract_driver` | Module 3 | `snapshot_from_driver` calls `await driver.navigate(url)` when URL differs and `await driver.get_page_source()` |
| `test_selenium_factory_returns_abstract_driver` | Module 4 | Registry `"selenium"` → `AbstractDriver` instance after `await setup.get_driver()` |
| `test_playwright_factory_returns_abstract_driver` | Module 4 | Still holds (regression guard) |
| `test_session_driver_is_abstract_driver` | Module 5 | `WebScrapingToolkit.start()` populates `_session_driver` with `AbstractDriver` |

### Integration Tests

| Test | Description |
|---|---|
| `test_executor_parity_selenium_vs_playwright_mock` | Register two fake AbstractDriver backends (Selenium-like, Playwright-like), run the same 5-step plan through each, assert that `_dispatch_step` called the same abstract methods in the same order with the same arguments |
| `test_toolkit_scrape_with_mock_abstract_driver` | Patch `driver_context` to yield a mock `AbstractDriver`; assert `scrape()` returns a valid `ScrapingResult` without Selenium or Playwright installed |
| `test_crawl_still_works_with_abstract_driver` | Smoke test against `CrawlEngine` path |

### Test Data / Fixtures

```python
# conftest-style abstract driver fake for parity tests
class FakeAbstractDriver(AbstractDriver):
    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []
        self._url = ""
        self._html = "<html><body><h1>ok</h1></body></html>"

    async def navigate(self, url, timeout=30):
        self.calls.append(("navigate", (url,), {"timeout": timeout}))
        self._url = url

    async def get_page_source(self):
        self.calls.append(("get_page_source", (), {}))
        return self._html

    @property
    def current_url(self):
        return self._url

    # ... remaining methods record-and-return
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] `grep -n "from selenium" packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`
      returns **zero** matches. All Selenium-specific imports live inside
      `SeleniumDriver`/`SeleniumSetup`.
- [ ] `grep -n "driver\.\(get\|page_source\|save_screenshot\|refresh\|switch_to\|find_element\)" packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`
      returns **zero** matches.
- [ ] `grep -n "driver\.\(page_source\|get\)" packages/ai-parrot-tools/src/parrot_tools/scraping/page_snapshot.py`
      returns **zero** matches for the `snapshot_from_driver` function body.
- [ ] `pytest packages/ai-parrot-tools/tests/scraping/ -v` passes (including
      updated executor/toolkit tests).
- [ ] `pytest tests/tools/scraping/ -v` passes.
- [ ] New parity test `test_executor_parity_selenium_vs_playwright_mock` passes.
- [ ] `DriverRegistry.get("selenium")(DriverConfig()).get_driver()` returns an
      instance of `AbstractDriver` (regression assertion in
      `test_selenium_factory_returns_abstract_driver`).
- [ ] Running `WebScrapingToolkit(driver_type="playwright", …).scrape(url=…, plan=…)`
      on a simple offline plan (with a mock `AbstractDriver`) produces a valid
      `ScrapingResult` — no `AttributeError` on `.get` / `.page_source`.
- [ ] No new public API surface. Signatures of `execute_plan_steps` and
      `snapshot_from_driver` unchanged except for driver type annotation.
- [ ] `.agent/CONTEXT.md` unchanged (this is internal plumbing).

---

## 6. Codebase Contract

### Verified Imports

```python
# Abstract driver surface — target API
from parrot_tools.scraping.drivers.abstract import AbstractDriver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py:11

from parrot_tools.scraping.drivers.selenium_driver import SeleniumDriver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py:20

from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py:15

from parrot_tools.scraping.drivers.playwright_config import PlaywrightConfig
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py:10

from parrot_tools.scraping.drivers import AbstractDriver, PlaywrightConfig, PlaywrightDriver, SeleniumDriver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/__init__.py:3-6

# Registry + lifecycle
from parrot_tools.scraping.driver_context import DriverRegistry, driver_context, _quit_driver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py:19, 125, 111

# Low-level selenium setup (kept internal)
from parrot_tools.scraping.driver import SeleniumSetup
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/driver.py:49

# Models
from parrot_tools.scraping.models import ScrapingResult, ScrapingSelector, ScrapingStep
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py:18-22

from parrot_tools.scraping.plan import ScrapingPlan
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py (imported at executor.py:23)

from parrot_tools.scraping.toolkit_models import DriverConfig
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py:15
```

### Existing Class Signatures

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py
class AbstractDriver(ABC):
    # Lifecycle
    async def start(self) -> None: ...                               # line 37
    async def quit(self) -> None: ...                                # line 41

    # Navigation
    async def navigate(self, url: str, timeout: int = 30) -> None: ...    # line 47
    async def go_back(self) -> None: ...                              # line 56
    async def go_forward(self) -> None: ...                           # line 60
    async def reload(self) -> None: ...                               # line 64

    # DOM interaction
    async def click(self, selector: str, timeout: int = 10) -> None: ...                        # line 70
    async def fill(self, selector: str, value: str, timeout: int = 10) -> None: ...             # line 79
    async def select_option(self, selector: str, value: str, timeout: int = 10) -> None: ...    # line 91  (to be extended)
    async def hover(self, selector: str, timeout: int = 10) -> None: ...                        # line 103
    async def press_key(self, key: str) -> None: ...                                             # line 112

    # Content
    async def get_page_source(self) -> str: ...                                                  # line 122
    async def get_text(self, selector: str, timeout: int = 10) -> str: ...                      # line 126
    async def get_attribute(self, selector: str, attribute: str, timeout: int = 10) -> Optional[str]: ...  # line 135
    async def get_all_texts(self, selector: str, timeout: int = 10) -> List[str]: ...           # line 150
    async def screenshot(self, path: str, full_page: bool = False) -> bytes: ...                # line 161

    # Waits
    async def wait_for_selector(self, selector: str, timeout: int = 10, state: str = "visible") -> None: ...  # line 177
    async def wait_for_navigation(self, timeout: int = 30) -> None: ...                         # line 190
    async def wait_for_load_state(self, state: str = "load", timeout: int = 30) -> None: ...    # line 198

    # Scripts
    async def execute_script(self, script: str, *args: Any) -> Any: ...                         # line 212
    async def evaluate(self, expression: str) -> Any: ...                                       # line 224

    # Property
    @property
    def current_url(self) -> str: ...                                                           # line 238
```

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py
class SeleniumDriver(AbstractDriver):                                 # line 20
    def __init__(
        self,
        browser: str = "chrome",
        headless: bool = True,
        auto_install: bool = True,
        mobile: bool = False,
        options: Optional[Dict[str, Any]] = None,
    ) -> None: ...                                                    # line 41
    async def start(self) -> None: ...                                # line 69 — builds SeleniumSetup then awaits get_driver()
    async def click(self, selector, timeout=10): ...                  # line 133 — TODO: add scrollIntoView fallback
    async def select_option(self, selector, value, timeout=10): ...   # line 148 — currently only by-value via selenium Select
```

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py
class PlaywrightDriver(AbstractDriver):                               # line 15
    def __init__(self, config: Optional[PlaywrightConfig] = None) -> None: ...  # line 30
    async def select_option(self, selector, value, timeout=10): ...   # line 112 — uses page.locator(sel).select_option(value, timeout=...)
```

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/driver_context.py
class DriverRegistry:                                                 # line 19
    _factories: Dict[str, Callable[[DriverConfig], Any]]              # line 31
    @classmethod
    def register(cls, driver_type: str, factory): ...                 # line 34
    @classmethod
    def get(cls, driver_type: str): ...                               # line 55

def _create_selenium_setup(config: DriverConfig) -> Any:              # line 84
    # returns SeleniumSetup — whose .get_driver() returns raw WebDriver  ← MUST CHANGE

class _PlaywrightSetup:                                               # line 97 (after recent add)
    async def get_driver(self) -> Any: ...                            # returns started PlaywrightDriver

async def _quit_driver(driver: Any) -> None: ...                      # line 141 — handles sync + async quit

…(truncated)…
