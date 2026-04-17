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

@asynccontextmanager
async def driver_context(config, session_driver=None): ...            # line 125
```

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py (current — to be rewritten)
async def execute_plan_steps(driver, plan=None, steps=None, selectors=None, config=None, base_url=None) -> ScrapingResult: ...
# line 33 — callers: WebScrapingToolkit.scrape(), WebScrapingToolkit.crawl via CrawlEngine

async def _dispatch_step(driver, step, base_url, timeout, step_extracted) -> bool: ...   # line 185
async def _action_navigate(driver, action, base_url, loop) -> bool: ...                  # line 256  → driver.get
async def _action_wait(driver, action, default_timeout, loop) -> bool: ...               # line 263  → WebDriverWait
async def _action_click(driver, action, default_timeout, loop) -> bool: ...              # line 333  → find_element + click
async def _action_fill(driver, action, default_timeout, loop) -> bool: ...               # line 370  → find_element + send_keys
async def _action_scroll(driver, action, loop) -> bool: ...                              # line 397  → execute_script (already JS-only)
async def _action_evaluate(driver, action, loop) -> bool: ...                            # line 419  → execute_script
async def _action_refresh(driver, action, loop) -> bool: ...                             # line 433  → driver.refresh
async def _action_back(driver, action, loop) -> bool: ...                                # line 445  → driver.back
async def _action_extract(driver, action, step, step_extracted, loop) -> bool: ...       # line 464  → driver.page_source
async def _action_screenshot(driver, action, loop) -> bool: ...                          # line 610  → driver.save_screenshot
async def _action_press_key(driver, action, loop) -> bool: ...                           # line 624  → switch_to.active_element
async def _action_select(driver, action, default_timeout, loop) -> bool: ...             # line 637  → selenium Select
async def _get_current_url(driver) -> str: ...                                           # line 714  → driver.current_url
async def _get_page_source(driver) -> str: ...                                           # line 720  → driver.page_source
```

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/page_snapshot.py
async def snapshot_from_driver(driver, url=None, *, settle_seconds=1.0) -> Optional[PageSnapshot]: ...
# line 483 — uses driver.current_url / driver.get(url) / driver.page_source
```

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py
class WebScrapingToolkit(AbstractToolkit):
    _session_driver: Optional[Any]      # line 138 — currently Any, will retype to Optional[AbstractDriver]
    async def start(self) -> None: ...   # line 146 — uses DriverRegistry.get(...).get_driver()
    async def stop(self) -> None: ...    # line 160 — uses _quit_driver
    async def scrape(...) -> ScrapingResult: ...   # line ~488, uses driver_context + execute_plan_steps + snapshot_from_driver
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| rewritten `_action_navigate` | `AbstractDriver.navigate` | `await driver.navigate(target, timeout=timeout)` | `drivers/abstract.py:47` |
| rewritten `_action_wait` (selector) | `AbstractDriver.wait_for_selector` | `await driver.wait_for_selector(sel, timeout, state="attached")` | `drivers/abstract.py:177` |
| rewritten `_action_click` | `AbstractDriver.click` | `await driver.click(locator, timeout)` | `drivers/abstract.py:70`; parity fallback in `SeleniumDriver.click` |
| rewritten `_action_fill` | `AbstractDriver.fill` | `await driver.fill(sel, value, timeout)` | `drivers/abstract.py:79` |
| rewritten `_action_evaluate` / `_action_scroll` | `AbstractDriver.execute_script` | `await driver.execute_script(script)` | `drivers/abstract.py:212` |
| rewritten `_action_refresh` | `AbstractDriver.reload` | `await driver.reload()` | `drivers/abstract.py:64` |
| rewritten `_action_back` | `AbstractDriver.go_back` | `await driver.go_back()` in loop | `drivers/abstract.py:56` |
| rewritten `_action_extract` | `AbstractDriver.get_page_source` | `html = await driver.get_page_source()` | `drivers/abstract.py:122` |
| rewritten `_action_screenshot` | `AbstractDriver.screenshot` | `await driver.screenshot(full_path)` | `drivers/abstract.py:161` |
| rewritten `_action_press_key` | `AbstractDriver.press_key` | `await driver.press_key(k)` per key | `drivers/abstract.py:112` |
| rewritten `_action_select` | `AbstractDriver.select_option` (extended `by=`) | `await driver.select_option(sel, v, by=..., timeout=...)` | `drivers/abstract.py:91` (extended in Task 2) |
| `_get_current_url` / `_get_page_source` | `AbstractDriver.current_url` / `.get_page_source` | property + awaited method | `drivers/abstract.py:238`, `drivers/abstract.py:122` |
| `snapshot_from_driver` | `AbstractDriver` | `await driver.navigate` / `get_page_source` / `current_url` | `page_snapshot.py:483` |
| `_SeleniumSetupAdapter.get_driver` | `SeleniumDriver` | `drv = SeleniumDriver(...); await drv.start(); return drv` | `drivers/selenium_driver.py:69` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AbstractDriver.page_source`~~ — it is `await get_page_source()`, not an attribute
- ~~`AbstractDriver.get(url)`~~ — the method is `navigate(url, timeout)`
- ~~`AbstractDriver.refresh()`~~ — the method is `reload()`
- ~~`AbstractDriver.back()`~~ — the method is `go_back()`
- ~~`AbstractDriver.find_element(...)`~~ — no such method; use higher-level `click/fill/get_text`
- ~~`AbstractDriver.save_screenshot(path)`~~ — the method is `screenshot(path, full_page=False)` and **returns bytes**
- ~~`AbstractDriver.switch_to`~~ — does not exist; `press_key` replaces the typical usage
- ~~`AbstractDriver.select_option(selector, by="text", ...)`~~ — the `by` kwarg DOES NOT exist yet; adding it is Module 2's explicit task
- ~~`SeleniumSetup` subclass of `AbstractDriver`~~ — it is the raw driver builder; the `AbstractDriver` wrapper is `SeleniumDriver`
- ~~`DriverFactory.create(config)` returning `AbstractDriver` is the path used by the toolkit~~ — the toolkit uses `DriverRegistry`, not `DriverFactory`; `DriverFactory` exists at `driver_factory.py:31` but is **not** on the toolkit's code path
- ~~`PlaywrightDriver.page_source` / `PlaywrightDriver.get(url)`~~ — Playwright exposes `page.goto` / `page.content` only through the `AbstractDriver` wrappers; the executor MUST NOT reach into `._page`
- ~~`WebDriverWait` usable against Playwright~~ — Selenium-only; must be removed from `executor.py`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first. All driver interactions inside the executor are `await`ed directly
  — no more `run_in_executor(None, driver.X, ...)` wrappers. Selenium blocking
  is absorbed inside `SeleniumDriver` where `self._run` already dispatches to an
  executor.
- Pydantic models stay authoritative for plan/step/selector shape.
- Logging via module-level `logger` (unchanged).
- Reuse existing `SeleniumDriver` internals for Selenium-side scroll-into-view
  fallback; do not duplicate that logic in the executor.
- When polling (`_wait_until`), use 0.25s poll frequency (matches the previous
  `WebDriverWait(poll_frequency=0.25)`).

### Known Risks / Gotchas

- **Risk: `AbstractDriver.click` does not scroll-into-view on Selenium.**
  The current executor branch does so manually for intercepted clicks. Mitigation:
  push the retry into `SeleniumDriver.click` (catch
  `ElementClickInterceptedException`, call
  `execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click();", element)`
  once, re-raise on second failure). Playwright's locator already handles this.
- **Risk: `select_option` API mismatch.** Playwright's `locator.select_option`
  accepts `value=`, `label=`, or `index=` keyword arguments; Selenium's `Select`
  has `select_by_value/visible_text/index`. Mitigation: extend abstract signature
  to `select_option(selector, value, *, by="value", timeout=10)` and dispatch
  inside each driver.
- **Risk: `_action_wait(condition_type="url_contains")` polling semantics.**
  The `WebDriverWait.until(EC.url_contains)` polls client-side. New
  `_wait_until` must poll `driver.current_url` (sync property on both drivers)
  in an async loop with `asyncio.sleep(0.25)` and respect the timeout.
- **Risk: Legacy `tool.py` still imports Selenium**. It is out of scope (`tool.py`
  bypasses `execute_plan_steps`). Tests for that module stay Selenium-dependent.
- **Risk: Session-driver lifecycle.** `WebScrapingToolkit.start()` (line 146)
  calls `setup.get_driver()` and stores the result as `_session_driver`. After
  Module 4's change, that stored object becomes an `AbstractDriver`. Verify
  `driver_context(session_driver=...)` yields it unchanged (already does).
- **Risk: Existing tests patch `driver_context` with a plain MagicMock**. Update
  fixtures to return an `AsyncMock` that satisfies `AbstractDriver` attribute
  lookups (`navigate`, `get_page_source`, `current_url`, `execute_script`,
  `reload`, `go_back`, `screenshot`, `press_key`, `click`, `fill`,
  `select_option`, `wait_for_selector`, `evaluate`).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `selenium` | (existing) | still required by `SeleniumDriver`/`SeleniumSetup` |
| `playwright` | (existing) | still required by `PlaywrightDriver` |
| `beautifulsoup4` | (existing) | HTML parsing in selector pipeline |

No new dependencies.

---

## 8. Open Questions

- [x] **Q1** — Should `_action_select` dispatch `by="value|text|index"` based on
      which of `action.value / action.text / action.index` is populated, or
      require `action.by` to be explicit? *Owner: Jesus Lara*: be explicit
- [x] **Q2** — For `condition_type="title_contains"`, do we keep the current
      implicit semantics (poll with fixed 0.25s interval) or expose a knob on
      `DriverConfig`? *Owner: Jesus Lara*: current semantics.
- [x] **Q3** — Should `_action_refresh(hard=True)` map to `driver.reload()`
      always (sufficient for Playwright) or keep the `location.reload(true)`
      script escape hatch for Selenium? Proposal: keep the `execute_script`
      fallback for parity. *Owner: Jesus Lara*: current fallback for parity.
- [x] **Q4** — Is parity with `WebScrapingTool` (legacy entry at `tool.py`)
      worth pursuing in a follow-up feature, or is it acceptable to let it
      remain Selenium-only until deprecated? *Owner: Jesus Lara*: remain selenium until the deprecation.

---

## Worktree Strategy

**Default isolation unit**: `per-spec`.

All tasks touch overlapping files (`executor.py`, `driver_context.py`, `toolkit.py`,
`page_snapshot.py`, `drivers/*.py`) and should run **sequentially in one worktree**
to avoid merge conflicts. Tests in Module 6 depend on every prior module.

Cross-feature dependencies: none pending. The `DriverRegistry` Playwright factory
addition (already on `dev`) is a prerequisite and is already landed.

Recommended worktree bootstrap:

```bash
git worktree add -b feat-104-fix-webscrapingtoolkit-executor \
  .claude/worktrees/feat-104-fix-webscrapingtoolkit-executor HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-17 | Jesus Lara | Initial draft |
