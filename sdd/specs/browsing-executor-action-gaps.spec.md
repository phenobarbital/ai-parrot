---
type: feature
base_branch: dev
projects: [ai-parrot-tools]
tags: [browsing, scraping, browser-actions, screenshot]
---

# Feature Specification: browsing-executor-action-gaps

**Feature ID**: FEAT-681
**Date**: 2026-10-15
**Author**: Jesus Lara
**Status**: draft
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

`WebBrowsingToolkit` (`parrot_tools/browsing/toolkit.py`) replays catalogued site
actions through `execute_plan_steps()` in `parrot_tools/scraping/executor.py`
(`browsing/toolkit.py:35`, `:646`). That executor has two gaps that make parts of
the `BrowserAction` DSL silently unusable from browsing (`run_site_action`,
`run_site_sequence`, `execute_web_task`):

1. **`hover`, `type` and `submit` are accepted but never executed.** The models
   `Hover`, `Type` and `Submit` exist (`scraping/models.py:79`, `:92`, `:245`) and are
   registered in `ACTION_MAP` (`models.py:772`), so `save_site_action` validates and
   stores scripts that use them. But `_dispatch_step` (`executor.py:264-377`) has no
   branch for any of the three: it falls through to
   `logger.warning("Unknown action type: %s", action_type)` and returns `False`
   (`executor.py:375-377`). A saved action that relies on them fails at run time with a
   generic "step returned False".
2. **`screenshot` only half works.** The `Screenshot` model (`models.py:587-612`)
   declares `selector`, `full_page` (default `True`), `output_path`, `output_name` and
   `return_base64`. `_action_screenshot` (`executor.py:869-880`) only uses
   `output_path`/`output_name`:
   - it calls `driver.screenshot(full_path)` without `full_page`, so the driver
     default `False` wins — Playwright captures only the viewport even though the
     model says full page by default;
   - `selector` is ignored — element screenshots are impossible;
   - `return_base64` is ignored and the path is never reported — the step returns only
     `True`, so the calling agent cannot see or locate the image.

### Goals
- `hover`, `type` and `submit` steps execute against every `AbstractDriver`
  implementation (Playwright, Page, Selenium) and honour their model fields.
- `screenshot` honours `full_page`, `selector` and `return_base64`, and always reports
  where the PNG was written in `ScrapingResult.extracted_data`.
- No `BrowserAction` registered in `ACTION_MAP` reaches the "Unknown action type"
  branch any more.

### Non-Goals (explicitly out of scope)
- Changing the legacy `WebScrapingTool` (`scraping/tool.py`) — browsing does not use it.
- Refactoring `_action_click`. Its text-contains path calls
  `driver.execute_script(script, selector, text)` with `arguments[0]`, which
  `page.evaluate(script, *args)` (Playwright/Page drivers) does not support. That is a
  separate defect: file it in the ledger, do not fix it here.
- Full-page screenshots on Selenium (`SeleniumDriver.screenshot` captures the viewport
  only; WebDriver has no portable full-page API).
- New DSL actions or model field changes — the three models and `Screenshot` stay as is.

---

## 2. Architectural Design

### Overview

Two layers change:

- **Drivers** gain two optional capabilities on `AbstractDriver`, as **concrete
  (non-abstract) methods whose base implementation raises `NotImplementedError`** so
  existing third-party/test subclasses of `AbstractDriver` (e.g. the fake driver in
  `tests/scraping/test_executor_driver_parity.py`) keep instantiating:
  - `type_text(text, selector=None, delay_ms=0, clear_first=False, timeout=10)` —
    keystroke-level typing (unlike `fill`, which sets the value at once);
  - `screenshot_element(selector, path, timeout=10) -> bytes` — PNG of one element.
  All three concrete drivers implement both.
- **Executor** gains `_action_hover`, `_action_type`, `_action_submit`, three new
  `_dispatch_step` branches, a small `_resolve_locator()` helper and a rewritten
  `_action_screenshot` that receives `step`/`step_extracted`.

Behaviour per action:

| Action | Behaviour |
|---|---|
| `hover` | Resolve the locator from `selector` + `selector_type` (`css` → BS4-only pseudos stripped, `xpath` → as is, `text` → `//*[contains(text(), '<sel>')]`, same mapping `_action_click` uses) and `await driver.hover(locator, timeout)`. |
| `type` | `await driver.type_text(action.text, selector=action.selector, delay_ms=action.delay, clear_first=action.clear_first, timeout=timeout)`. With `selector=None` it types into the focused element. |
| `submit` | Run one `driver.evaluate()` IIFE (selector embedded with `json.dumps`, **not** passed as an argument — see §7) that resolves the selector (XPath via `document.evaluate` when it starts with `/` or `./`, else `querySelector`) and returns `"missing"`, `"form"` (element is a `<form>`: `requestSubmit()` when available, else `submit()`) or `"click"`. `"missing"` → raise `RuntimeError`; `"click"` → `await driver.click(selector, timeout)`. Then, if `wait_after_submit` is set, `await driver.wait_for_selector(wait_after_submit, action.wait_timeout)`. |
| `screenshot` | Build the confined path as today. If `selector` is set → `driver.screenshot_element(selector, path, timeout)`; else `driver.screenshot(path, full_page=action.full_page)`. Record `{"path": <str>}` (plus `"base64": <str>` when `return_base64`) in `step_extracted` under the key `action.name` (when it is not the default `"screenshot"`) or `"screenshot"`; on key collision append `_2`, `_3`, … |

### Component Diagram
```
WebBrowsingToolkit.run_site_action / run_site_sequence / execute_web_task
        │
        ▼
execute_plan_steps ──→ _dispatch_step ──┬─→ _action_hover    ──→ driver.hover
                                        ├─→ _action_type     ──→ driver.type_text        (new)
                                        ├─→ _action_submit   ──→ driver.evaluate / click / wait_for_selector
                                        └─→ _action_screenshot ─→ driver.screenshot(full_page) | driver.screenshot_element (new)
                                                    │
                                                    └─→ step_extracted[key] = {"path", "base64"?} ──→ ScrapingResult.extracted_data
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractDriver` | extends (2 concrete methods) | non-abstract, default raises `NotImplementedError` |
| `PlaywrightDriver`, `PageDriver`, `SeleniumDriver` | implement | `type_text`, `screenshot_element` |
| `_dispatch_step` | modifies | three new `elif` branches; screenshot branch passes `step`, `step_extracted` |
| `confined_file` | uses (unchanged) | screenshot path still confined to `<plans_dir>/files` |
| `WebBrowsingToolkit` | none (consumer) | already forwards `result.extracted_data` (`browsing/toolkit.py:667`) |

### Data Models

No model changes. Shape of a screenshot entry in `extracted_data`:
```python
{"path": "/…/files/screenshots/page.png"}                       # default
{"path": "/…/files/screenshots/page.png", "base64": "iVBORw0…"}  # return_base64=True
```

### New Public Interfaces
```python
class AbstractDriver(ABC):
    async def type_text(self, text: str, selector: Optional[str] = None, delay_ms: int = 0,
                        clear_first: bool = False, timeout: int = 10) -> None: ...
    async def screenshot_element(self, selector: str, path: str, timeout: int = 10) -> bytes: ...
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Driver capabilities | yes | Signatures in skeleton; base raises `NotImplementedError`; Playwright `locator.press_sequentially` / `keyboard.type` / `locator.screenshot`; Selenium `send_keys` / `element.screenshot`; selectors via each driver's existing `_resolve_selector` / `_find_element` | — |
| M2: Executor handlers | yes | Behaviour table in §2; dispatch anchors in §6; screenshot key rule and payload fixed | — |
| M3: Tests | yes | Test tables in §4; regression-test rewrite rule in §7 | — |

### Module 1: Driver capabilities
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/{abstract,playwright_driver,page_driver,selenium_driver}.py`
- **Responsibility**: keystroke typing and element screenshots on every driver.
- **Depends on**: existing `AbstractDriver`.
- **Interface Skeleton**:
  ```python
  # drivers/abstract.py  (modifies; insert after `screenshot` at abstract.py:163)
  class AbstractDriver(ABC):  # verified: drivers/abstract.py:11
      async def type_text(
          self,
          text: str,
          selector: Optional[str] = None,
          delay_ms: int = 0,
          clear_first: bool = False,
          timeout: int = 10,
      ) -> None:
          """Type *text* keystroke by keystroke.

          Args:
              text: Characters to type.
              selector: Element to focus first (CSS or XPath); ``None`` types into the
                  currently focused element.
              delay_ms: Delay between key presses in milliseconds.
              clear_first: Clear the element's value before typing (requires *selector*).
              timeout: Seconds to wait for *selector*.

          Raises:
              NotImplementedError: Base implementation; concrete drivers override it.
          """

      async def screenshot_element(self, selector: str, path: str, timeout: int = 10) -> bytes:
          """Capture a PNG of the element matching *selector* and save it to *path*.

          Returns:
              Raw PNG bytes.

          Raises:
              NotImplementedError: Base implementation; concrete drivers override it.
          """

  # drivers/playwright_driver.py  (modifies; PlaywrightDriver verified: playwright_driver.py:15)
  #   type_text: locator(self._resolve_selector(sel)); clear_first → fill(""); press_sequentially(text, delay=delay_ms,
  #              timeout=timeout*1000); selector None → self._page.keyboard.type(text, delay=delay_ms)
  #   screenshot_element: self._page.locator(self._resolve_selector(sel)).screenshot(path=path, timeout=timeout*1000)
  # drivers/page_driver.py        (modifies; PageDriver verified: page_driver.py:19) — same as Playwright
  # drivers/selenium_driver.py    (modifies; SeleniumDriver verified: selenium_driver.py:20)
  #   type_text: _wait_for_element + _find_element; clear_first → element.clear; send_keys per character with
  #              asyncio.sleep(delay_ms/1000) between keys when delay_ms > 0; selector None → switch_to.active_element
  #   screenshot_element: element.screenshot_as_png, written to *path* (blocking calls via self._run)
  ```

### Module 2: Executor handlers
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`
- **Responsibility**: dispatch and execute `hover`, `type`, `submit`; complete `screenshot`.
- **Depends on**: Module 1 (`type_text`, `screenshot_element`).
- **Interface Skeleton**:
  ```python
  # executor.py (modifies)
  def _resolve_locator(selector: str, selector_type: str = "css") -> str:
      """Map a DSL selector + selector_type to a driver locator.

      css → BS4-only pseudo-classes stripped (via _strip_soup_only_pseudos, executor.py:954);
      xpath → unchanged; text → ``//*[contains(text(), '<selector>')]``.
      """

  async def _action_hover(driver: AbstractDriver, action: Any, default_timeout: int) -> bool:
      """Hover over the element resolved from ``action.selector``/``selector_type``."""

  async def _action_type(driver: AbstractDriver, action: Any, default_timeout: int) -> bool:
      """Type ``action.text`` via ``driver.type_text`` honouring selector/delay/clear_first."""

  async def _action_submit(driver: AbstractDriver, action: Any, default_timeout: int) -> bool:
      """Submit a form (requestSubmit) or click a submit control; optional post-submit wait.

      Raises:
          RuntimeError: when the selector matches no element.
      """

  async def _action_screenshot(  # replaces executor.py:869
      driver: AbstractDriver,
      action: Any,
      step: ScrapingStep,
      step_extracted: Dict[str, Any],
  ) -> bool:
      """Capture page (full_page honoured) or element; record path (+ base64) in step_extracted."""
  ```

### Module 3: Tests
- **Path**: `packages/ai-parrot-tools/tests/scraping/test_executor_action_gaps.py` (new),
  `tests/scraping/test_driver_type_and_element_screenshot.py` (new),
  `tests/scraping/test_stub_closure_regression.py` (modify `test_unknown_action_returns_false`).
- **Responsibility**: cover §4.
- **Depends on**: Modules 1 and 2.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_hover_css_calls_driver_hover` | M2 | `hover` step → `driver.hover("#x", timeout)` and step succeeds |
| `test_hover_text_selector_builds_xpath` | M2 | `selector_type="text"` → `//*[contains(text(), 'Menu')]` |
| `test_type_forwards_all_fields` | M2 | `type` → `driver.type_text(text, selector=…, delay_ms=…, clear_first=…, timeout=…)` |
| `test_type_without_selector` | M2 | `selector=None` forwarded as `None` |
| `test_submit_form_uses_request_submit` | M2 | evaluate returns `"form"` → no `driver.click`, step succeeds |
| `test_submit_button_clicks` | M2 | evaluate returns `"click"` → `driver.click(selector, timeout)` |
| `test_submit_missing_records_error` | M2 | evaluate returns `"missing"` → `step_errors` entry, plan not aborted |
| `test_submit_waits_after` | M2 | `wait_after_submit` → `driver.wait_for_selector(sel, wait_timeout)` |
| `test_submit_selector_is_json_embedded` | M2 | evaluate expression contains `json.dumps(selector)`; `execute_script` not called |
| `test_screenshot_passes_full_page` | M2 | default → `driver.screenshot(path, full_page=True)`; `full_page=False` forwarded |
| `test_screenshot_element_uses_screenshot_element` | M2 | `selector` set → `driver.screenshot_element(selector, path, timeout)`; `driver.screenshot` not called |
| `test_screenshot_records_path` | M2 | `extracted_data["screenshot"]["path"]` is the confined path; no `base64` key |
| `test_screenshot_return_base64` | M2 | `return_base64=True` → `base64` decodes to the driver's bytes |
| `test_screenshot_key_collision_suffix` | M2 | two screenshots → keys `screenshot`, `screenshot_2` |
| `test_screenshot_custom_name_key` | M2 | `name="home"` → key `home` |
| `test_every_action_map_entry_is_dispatched` | M2 | for every `ACTION_MAP` key, `_dispatch_step` source has an `action_type == "<key>"` branch |
| `test_unknown_action_returns_false` (rewritten) | M3 | uses an action whose `get_action_type()` returns an opcode absent from `ACTION_MAP` (no longer `"hover"`) |
| `test_abstract_driver_defaults_raise` | M1 | a minimal `AbstractDriver` subclass raises `NotImplementedError` for both new methods |
| `test_playwright_type_text_with_selector` | M1 | mocked page/locator: `fill("")` when `clear_first`, then `press_sequentially(text, delay=…)` |
| `test_playwright_type_text_focused` | M1 | `selector=None` → `page.keyboard.type(text, delay=…)` |
| `test_playwright_screenshot_element` | M1 | `locator(sel).screenshot(path=…, timeout=…)` |
| `test_selenium_type_text_and_screenshot_element` | M1 | mocked WebDriver element: `clear`, `send_keys`, `screenshot_as_png` written to path |

### Integration Tests
| Test | Description |
|---|---|
| `test_browsing_sequence_hover_type_submit_screenshot` | Local fixture page (`tests/scraping/fixtures`) driven by `PlaywrightDriver` (skipped when Playwright browsers are absent): hover reveals a menu, type fills an input, submit posts the form, element + full-page screenshots written and reported |

### Test Data / Fixtures
```python
@pytest.fixture
def spy_driver():  # same shape as tests/scraping/test_stub_closure_regression.py:47
    driver = AsyncMock()
    driver.get_page_source = AsyncMock(return_value="<html></html>")
    driver.current_url = "http://x/"
    driver.screenshot = AsyncMock(return_value=b"\x89PNG")
    driver.screenshot_element = AsyncMock(return_value=b"\x89PNG")
    return driver
```

---

## 5. Acceptance Criteria

- [ ] A plan with `hover`, `type` and `submit` steps executes them through the driver; none logs "Unknown action type".
- [ ] Every key of `ACTION_MAP` has a branch in `_dispatch_step` (enforced by `test_every_action_map_entry_is_dispatched`).
- [ ] `submit` on a `<form>` submits it without clicking; on any other element clicks it; on no match records a step error.
- [ ] `submit` never passes arguments to `execute_script` (works under `page.evaluate`).
- [ ] `screenshot` forwards `full_page` to `driver.screenshot`.
- [ ] `screenshot` with `selector` captures only that element via `driver.screenshot_element`.
- [ ] Every `screenshot` step adds `{"path": …}` to `extracted_data`; with `return_base64=True` it also adds `"base64"`.
- [ ] The screenshot path is still confined by `confined_file` (no behaviour change to confinement).
- [ ] `AbstractDriver` subclasses that do not implement the new methods still instantiate (methods are not abstract).
- [ ] `PlaywrightDriver`, `PageDriver` and `SeleniumDriver` implement `type_text` and `screenshot_element`.
- [ ] `pytest packages/ai-parrot-tools/tests/scraping/ -q` passes; `ruff check` clean on touched files.
- [ ] No breaking change to existing public signatures (`execute_plan_steps`, `AbstractDriver.screenshot`, models).

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot_tools.scraping.executor import execute_plan_steps  # verified: browsing/toolkit.py:35
from parrot_tools.scraping.plan import ScrapingPlan            # verified: tests/scraping/test_stub_closure_regression.py:16
from parrot_tools.scraping import executor as executor_module  # verified: tests/scraping/test_stub_closure_regression.py:14
from parrot_tools.scraping.models import ACTION_MAP            # verified: scraping/models.py:772
from parrot_tools.scraping.drivers.abstract import AbstractDriver  # verified: drivers/abstract.py:11
```

### Existing Class Signatures
```python
# scraping/models.py
class Hover(BrowserAction):            # line 79
    selector: str
    selector_type: Literal["css", "xpath", "text"] = "css"
class Type(BrowserAction):             # line 92
    text: str
    selector: Optional[str] = None
    delay: int = 0                     # milliseconds between key presses
    clear_first: bool = False
class Submit(BrowserAction):           # line 245
    selector: str                      # form or submit control; NO selector_type field
    wait_after_submit: Optional[str] = None
    wait_timeout: int = 5
class Screenshot(BrowserAction):       # line 587
    selector: Optional[str] = None
    full_page: bool = True
    output_path: Optional[str] = None
    output_name: Optional[str] = None
    return_base64: bool = False
    def get_filename(self) -> str: ... # line 606
BrowserAction.timeout: Optional[int]  # line 22
BrowserAction.get_action_type() -> str  # line 26 — reads `action`, not `name`

# scraping/drivers/abstract.py
class AbstractDriver(ABC):                                        # line 11
    async def click(self, selector: str, timeout: int = 10) -> None            # line 70
    async def fill(self, selector: str, value: str, timeout: int = 10) -> None # line 79
    async def hover(self, selector: str, timeout: int = 10) -> None            # line 109 (abstract)
    async def press_key(self, key: str) -> None                                # line 118
    async def screenshot(self, path: str, full_page: bool = False) -> bytes    # line 163 (abstract)
    async def wait_for_selector(self, selector: str, timeout: int = 10, state: str = "visible") -> None  # line 177
    async def execute_script(self, script: str, *args: Any) -> Any            # line 208
    async def evaluate(self, expression: str) -> Any                           # line 220

# Concrete drivers
PlaywrightDriver._resolve_selector(self, selector) -> str   # playwright_driver.py:456 — '/'/'./' → 'xpath=…'
PlaywrightDriver.screenshot → self._page.screenshot(path=path, full_page=full_page)  # playwright_driver.py:244
PlaywrightDriver.execute_script → self._page.evaluate(script, *args)                # playwright_driver.py:265
PageDriver._resolve_selector(selector) -> str  (staticmethod)  # page_driver.py:34
PageDriver.screenshot                                          # page_driver.py:147
SeleniumDriver._find_element(self, selector) (blocking)       # selenium_driver.py:117 — XPath when '/'/'./'
SeleniumDriver._wait_for_element(selector, timeout)            # used at selenium_driver.py:170
SeleniumDriver._run(fn, *args)                                 # blocking-call bridge, used throughout
SeleniumDriver.screenshot(self, path, full_page=False) -> bytes  # selenium_driver.py:273 — viewport only
SeleniumDriver.evaluate → execute_script(f"return {expression}")  # selenium_driver.py:368

# scraping/executor.py
async def execute_plan_steps(driver, plan=None, steps=None, selectors=None, config=None,
                             base_url=None, credential_resolver=None, channel=None) -> ScrapingResult  # line 60
async def _dispatch_step(driver, step, base_url, timeout, step_extracted, *, credential_resolver=None,
                         channel=None) -> bool                                  # line 264
async def _action_click(driver, action, default_timeout) -> bool                # line 449 (text→xpath mapping to mirror)
async def _action_fill(driver, action, default_timeout) -> bool                 # line 519
async def _action_get_cookies(driver, action, step, step_extracted) -> bool     # line 624 (step_extracted pattern)
async def _action_screenshot(driver, action) -> bool                            # line 869 (to be replaced)
def _strip_soup_only_pseudos(selector: str) -> str                              # line 954
from .confine import check_navigation, confined_file                            # line 383
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_action_hover` | `AbstractDriver.hover` | await | `drivers/abstract.py:109` |
| `_action_type` | `AbstractDriver.type_text` (new, M1) | await | — |
| `_action_submit` | `AbstractDriver.evaluate`, `.click`, `.wait_for_selector` | await | `abstract.py:220`, `:70`, `:177` |
| `_action_screenshot` | `AbstractDriver.screenshot(path, full_page=…)` / `.screenshot_element` (new) | await | `abstract.py:163` |
| screenshot payload | `ScrapingResult.extracted_data` | `step_extracted` dict merged at `executor.py:194` | `executor.py:194` |

### Does NOT Exist (Anti-Hallucination)
- ~~`_action_hover` / `_action_type` / `_action_submit`~~ — not in `executor.py` today.
- ~~`AbstractDriver.type_text` / `AbstractDriver.screenshot_element`~~ — added by M1.
- ~~`AbstractDriver.submit`~~ — no driver-level submit; do not add one.
- ~~`Submit.selector_type`~~ — `Submit` has only `selector`.
- ~~`hover`/`type`/`submit` handlers in `scraping/tool.py`~~ — the legacy tool has none either; there is no reference implementation to copy.
- ~~Passing extra args to `driver.execute_script` under Playwright~~ — `page.evaluate` takes one optional arg; `arguments[0]` is undefined there.

### Edit Sites (Blueprint Anchors)

Verified against: `181922474`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | MODIFY | `    elif action_type == "screenshot":` | `executor.py:317` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | MODIFY | `        logger.warning("Unknown action type: %s", action_type)` | `executor.py:376` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | MODIFY | `async def _action_screenshot(driver: AbstractDriver, action: Any) -> bool:` | `executor.py:869` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py` | MODIFY | `    async def screenshot(self, path: str, full_page: bool = False) -> bytes:` | `abstract.py:163` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` | MODIFY | `    async def screenshot(self, path: str, full_page: bool = False) -> bytes:` | `playwright_driver.py:244` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/page_driver.py` | MODIFY | `    async def screenshot(self, path: str, full_page: bool = False) -> bytes:` | `page_driver.py:147` | 1 |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py` | MODIFY | `    async def screenshot(` | `selenium_driver.py:273` | 1 |
| `packages/ai-parrot-tools/tests/scraping/test_stub_closure_regression.py` | MODIFY | `    async def test_unknown_action_returns_false(self, spy_driver):` | `test_stub_closure_regression.py:85` | 1 |
| `packages/ai-parrot-tools/tests/scraping/test_executor_action_gaps.py` | CREATE | — | — | — |
| `packages/ai-parrot-tools/tests/scraping/test_driver_type_and_element_screenshot.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Handlers follow the existing `_action_*` shape: `async def …(driver, action, default_timeout) -> bool`,
  `timeout = action.timeout or default_timeout`, return `True` on success, raise on hard failure
  (the loop at `executor.py:142-176` turns exceptions into `step_errors`).
- `step_extracted` writes follow `_action_get_cookies` (`executor.py:624`).
- Selenium blocking calls go through `self._run(...)`; never block the event loop.
- `self.logger`/module `logger`, never `print`; Google docstrings; 120 columns.

### Known Risks / Gotchas
- **`execute_script` with args is not portable.** Playwright/Page drivers map it to
  `page.evaluate(script, *args)`. `submit` must use `driver.evaluate()` with the selector
  embedded via `json.dumps` inside an IIFE expression (`(() => { … })()`), which works in both
  Playwright (`page.evaluate(expr)`) and Selenium (`execute_script("return " + expr)`).
- **`test_unknown_action_returns_false` uses `"hover"`** as its "unknown to the dispatcher"
  example (`test_stub_closure_regression.py:86-90`). Once hover is dispatched that test no longer
  exercises the else branch; it must switch to an opcode that is not in `ACTION_MAP`.
- **Base64 payload size.** A full-page PNG can be several MB; with `return_base64=True` it travels
  through `extracted_data` into the MCP response of `run_site_action`. Default stays `False`; the
  model's field description and the browsing readme should say so (see §8 Q1).
- **`full_page` default flips effective behaviour.** Plans that relied on the accidental
  viewport-only capture will now get full-page images (the model default is `True`). Intentional:
  it aligns runtime with the declared contract.
- **Selenium `full_page`** stays viewport-only; log a debug line when `full_page=True` on Selenium,
  do not fail.
- **`Type.delay` is milliseconds**; Playwright `delay` is ms too, Selenium sleeps need `/1000`.

### External Dependencies
None new. `Locator.press_sequentially` needs playwright ≥ 1.38; the venv has 1.52.0.

---

## 8. Open Questions

- [ ] Should `return_base64` be capped (e.g. refuse/skip base64 above N MB and return only the path) to protect MCP response size? — *Owner: Jesus Lara*
- [ ] Should the out-of-scope `_action_click` text-contains `execute_script(script, *args)` incompatibility with Playwright be filed in the ledger now? — *Owner: Jesus Lara*

---

## Worktree Strategy

- **Isolation**: one feature worktree (`feat-FEAT-681-browsing-executor-action-gaps`); the sdd-coder
  engine gives each task its own sub-worktree.
- **Module dependency graph**: M2 → M1 (`_action_type` / `_action_screenshot` call
  `type_text` / `screenshot_element`); M3 → M1, M2. Hover and submit handlers of M2 only use
  existing driver methods, so a split M2 task for them could run concurrently with M1.
- **Shared files**: `executor.py` (all M2 handlers — serialize M2 tasks); `drivers/abstract.py` (M1 only).
- **Exclusive resources**: none.
- **Cross-feature dependencies**: none.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted brainstorm/proposal for this feature; spec seeded from a code review in-session)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-15 | Jesus Lara | Initial draft |
