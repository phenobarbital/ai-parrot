# TASK-729: Rewrite `executor.py` against `AbstractDriver`

**Feature**: fix-webscrapingtoolkit-executor
**Spec**: `sdd/specs/fix-webscrapingtoolkit-executor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-727, TASK-728
**Assigned-to**: unassigned

---

## Context

`packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` currently calls
Selenium-only APIs directly on the `driver` argument. After TASK-728 the
registry hands out an `AbstractDriver`, and after TASK-727 the abstract
`select_option(by=...)` exists. This task rewrites every action handler so the
executor consumes ONLY the `AbstractDriver` contract.

Implements **Module 1** of the spec.

---

## Scope

Rewrite each action handler in `executor.py` per the spec's mapping table
(Module 1). Specifically:

- `_action_navigate` → `await driver.navigate(target, timeout=...)`
- `_action_wait`:
  - `condition_type == "simple"` → `await asyncio.sleep(wait_timeout)`
  - `condition_type == "selector"` → `await driver.wait_for_selector(sel, timeout=wait_timeout, state="attached")` (keep `_strip_soup_only_pseudos` rescue logic)
  - `condition_type == "url_contains"` → new helper `await _wait_until(lambda: substring in driver.current_url, timeout=...)`
  - `condition_type == "title_contains"` → `await _wait_until(async lambda: substring in (await driver.evaluate("document.title")), ...)`
- `_action_click` → `await driver.click(selector, timeout)` (Selenium scrollIntoView fallback now lives in `SeleniumDriver.click` per TASK-727)
- `_action_fill` → `await driver.fill(selector, value, timeout)` (handle `clear_first` and `press_enter`: when `press_enter`, follow with `await driver.press_key("Enter")`)
- `_action_scroll` → `await driver.execute_script(script)` (script generation logic stays the same)
- `_action_evaluate` → `await driver.execute_script(script)`
- `_action_refresh` → `await driver.reload()` (and `await driver.execute_script("location.reload(true)")` when `hard=True`, per Q3 in spec)
- `_action_back` → `for _ in range(n): await driver.go_back()`
- `_action_extract` → `html = await driver.get_page_source()`
- `_action_screenshot` → `await driver.screenshot(full_path)`
- `_action_press_key` → `for k in action.keys: await driver.press_key(k)`
- `_action_select` → `await driver.select_option(selector, value, by=by, timeout=timeout)` (by-resolution: explicit `action.by` if set, else infer from which of `value/text/index` is populated — Q1)
- `_get_current_url` → `return driver.current_url`
- `_get_page_source` → `return await driver.get_page_source()`

Add module-private async helper:

```python
async def _wait_until(predicate, timeout: int, poll: float = 0.25) -> None:
    """Poll an async predicate until it returns True or raise asyncio.TimeoutError."""
```

Remove all `loop = asyncio.get_running_loop()` / `loop.run_in_executor(None, driver.X, ...)` calls — `AbstractDriver` methods are already async.

Remove all top-of-file `from selenium...` imports inside action handlers
(none should remain in `executor.py`).

**NOT in scope**:
- Modifying `snapshot_from_driver` (TASK-730)
- Modifying `WebScrapingToolkit` typing (TASK-731)
- Modifying tests (TASK-732)
- Changing `BrowserAction` / `ScrapingStep` model shape

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | MODIFY | Full internal rewrite per spec mapping table |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.drivers.abstract import AbstractDriver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py:11

from parrot_tools.scraping.models import ScrapingResult, ScrapingSelector, ScrapingStep
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py:18-22

from parrot_tools.scraping.plan import ScrapingPlan
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py:23

from parrot_tools.scraping.toolkit_models import DriverConfig
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py:15

# bs4 stays — extraction is HTML-side
from bs4 import BeautifulSoup
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py
class AbstractDriver(ABC):
    async def navigate(self, url: str, timeout: int = 30) -> None: ...           # line 47
    async def go_back(self) -> None: ...                                          # line 56
    async def reload(self) -> None: ...                                           # line 64
    async def click(self, selector: str, timeout: int = 10) -> None: ...          # line 70
    async def fill(self, selector: str, value: str, timeout: int = 10) -> None: ...   # line 79
    async def select_option(self, selector: str, value: str, *, by: str = "value", timeout: int = 10) -> None: ...  # extended by TASK-727
    async def press_key(self, key: str) -> None: ...                              # line 112
    async def get_page_source(self) -> str: ...                                   # line 122
    async def screenshot(self, path: str, full_page: bool = False) -> bytes: ... # line 161
    async def wait_for_selector(self, selector: str, timeout: int = 10, state: str = "visible") -> None: ...  # line 177
    async def execute_script(self, script: str, *args: Any) -> Any: ...           # line 212
    async def evaluate(self, expression: str) -> Any: ...                         # line 224
    @property
    def current_url(self) -> str: ...                                             # line 238

# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py — unchanged; the
# action types referenced by the dispatch table:
#   Navigate.url, Wait.condition / condition_type / timeout,
#   Click.selector / selector_type, Fill.selector / value / clear_first / press_enter,
#   Scroll.direction / amount, Refresh.hard, Back.steps,
#   Screenshot.output_path / get_filename(), PressKey.keys,
#   Select.selector / by / value / text / index / timeout,
#   Extract.selector / fields / extract_type / multiple / extract_name
```

### Does NOT Exist
- ~~`AbstractDriver.get(url)` / `.refresh()` / `.back()` / `.page_source` / `.save_screenshot()`~~ — these are the renamed methods documented in spec Section 6's "Does NOT Exist" list
- ~~`AbstractDriver.find_element` / `.switch_to`~~ — high-level methods only
- ~~`AbstractDriver.wait_for_url_contains` / `.wait_for_title_contains`~~ — implement with the new `_wait_until` helper, NOT on the abstract surface
- ~~`asyncio.get_running_loop().run_in_executor(None, driver.X, ...)`~~ — no longer needed; `AbstractDriver` methods are awaited directly
- ~~`from selenium.webdriver.support import expected_conditions as EC` inside `executor.py`~~ — must NOT be present after rewrite

---

## Implementation Notes

### Pattern to Follow

```python
# Rewritten _action_navigate
async def _action_navigate(driver: AbstractDriver, action: Any, base_url: str) -> bool:
    target = urljoin(base_url, action.url) if base_url else action.url
    timeout = getattr(action, "timeout", None) or 30
    await driver.navigate(target, timeout=timeout)
    return True


# New helper
async def _wait_until(predicate, timeout: int, poll: float = 0.25) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return
        if asyncio.get_event_loop().time() >= deadline:
            raise asyncio.TimeoutError(f"_wait_until timed out after {timeout}s")
        await asyncio.sleep(poll)


# _action_select with by-inference (Q1 default)
async def _action_select(driver: AbstractDriver, action: Any, default_timeout: int) -> bool:
    by = getattr(action, "by", None) or (
        "value" if action.value
        else "text" if getattr(action, "text", None)
        else "index" if getattr(action, "index", None) is not None
        else "value"
    )
    raw = (
        action.value if by == "value"
        else action.text if by == "text"
        else str(action.index)
    )
    timeout = action.timeout or default_timeout
    await driver.select_option(action.selector, raw, by=by, timeout=timeout)
    return True
```

### Key Constraints

- Drop the `loop` parameter from every `_action_*` helper (no executor needed).
- Keep all existing logging messages + error-collection semantics. The error
  list shape (`{"step_index", "action", "error"}`) must remain identical.
- Keep `_normalize_bs4_selector`, `_strip_soup_only_pseudos`, `_apply_field`,
  `_extract_node_value`, `_apply_selectors` — these operate on `BeautifulSoup`
  output, not on the driver, and are already driver-agnostic.
- The current `_action_wait(condition_type="selector")` warns when soupsieve
  pseudos appear in a Selenium-targeted selector. Keep that warning — the
  rationale (Selenium's CSS engine) still applies because `wait_for_selector`
  is implemented in `SeleniumDriver` via `WebDriverWait`. For Playwright the
  pseudos may also fail; the rescue is still appropriate.
- For `condition_type == "selector"` use `state="attached"` (matches today's
  `EC.presence_of_element_located` semantics).

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` — current Selenium-coupled implementation to rewrite
- `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py:236-313` — Selenium driver's wait/click implementations (already proven equivalents)
- `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py:170-189` — Playwright driver's wait implementations

---

## Acceptance Criteria

- [ ] `grep -n "from selenium" packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` → zero matches.
- [ ] `grep -nE "driver\.(get|page_source|save_screenshot|refresh|switch_to|find_element)" packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` → zero matches.
- [ ] `grep -n "run_in_executor" packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` → zero matches.
- [ ] `grep -n "WebDriverWait" packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` → zero matches.
- [ ] `python -c "from parrot_tools.scraping.executor import execute_plan_steps"` succeeds with no Selenium import side-effects.
- [ ] All callers (`WebScrapingToolkit`, `CrawlEngine`) compile (no signature change).

---

## Test Specification

The exhaustive test rewrite happens in TASK-732. For this task, smoke-test
manually with a `FakeAbstractDriver` (record-and-return) to confirm:

```python
class FakeAbstractDriver(AbstractDriver):
    def __init__(self):
        self.calls = []
        self._url = ""
    async def navigate(self, url, timeout=30):
        self.calls.append(("navigate", url))
        self._url = url
    async def get_page_source(self):
        self.calls.append(("get_page_source",))
        return "<html><body><h1>ok</h1></body></html>"
    @property
    def current_url(self):
        return self._url
    # ... record-and-return for every other abstract method
```

Run the existing `pytest packages/ai-parrot-tools/tests/scraping/test_executor.py`
suite — fixtures will fail until TASK-732 updates them. That is expected;
this task is complete when imports + signatures are correct, NOT when the old
Selenium-mock tests pass.

---

## Agent Instructions

1. Read spec Module 1 + the executor mapping table.
2. Confirm TASK-727 (extended `select_option`) and TASK-728 (Selenium adapter)
   are in `sdd/tasks/completed/` before starting.
3. Verify every signature in the contract with `read` first.
4. Implement the rewrite. Do NOT touch `page_snapshot.py` or `toolkit.py`.
5. Smoke-test imports.
6. Move file to `sdd/tasks/completed/`.

---

## Completion Note

Completed 2026-04-17. Rewrote executor.py internals to consume only AbstractDriver interface.
All Selenium-specific imports removed. Added _wait_until async polling helper.
Dropped loop parameter from all action handlers. Import smoke test passes.
Acceptance criteria verified: zero matches for from selenium, run_in_executor,
and forbidden driver.* patterns (driver.get_page_source matches the regex but is a
valid AbstractDriver call — the regex in the acceptance criteria has a known
imprecision with get_page_source vs bare driver.get(url)).
