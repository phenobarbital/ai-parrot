# TASK-727: Extend AbstractDriver `select_option(by=...)` and SeleniumDriver scrollIntoView click fallback

**Feature**: fix-webscrapingtoolkit-executor
**Spec**: `sdd/specs/fix-webscrapingtoolkit-executor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The executor's `_action_select` (today at `executor.py:637`) supports
`by="value"` / `"text"` / `"index"` via Selenium's `Select`, while
`AbstractDriver.select_option` (`drivers/abstract.py:91`) only takes a single
`value`. To rewrite the executor against `AbstractDriver` (TASK-729) we must
first widen the abstract contract. Similarly, the executor's `_action_click`
(today at `executor.py:333`) falls back to JS `scrollIntoView` + click on
`ElementClickInterceptedException`. Centralize that retry inside
`SeleniumDriver.click` so the executor doesn't need to know.

Implements **Module 2** of the spec.

---

## Scope

- Extend `AbstractDriver.select_option(self, selector, value, *, by="value", timeout=10)` — keep `value` positional/required, accept new keyword `by: Literal["value", "text", "index"] = "value"`.
- Update `SeleniumDriver.select_option` to dispatch on `by` to `select_by_value` / `select_by_visible_text` / `select_by_index` (the latter requires `int(value)`).
- Update `PlaywrightDriver.select_option` to dispatch on `by` to Playwright `locator.select_option(value=...)`, `select_option(label=...)`, `select_option(index=int(value))`.
- Add scroll-into-view + retry once fallback inside `SeleniumDriver.click` for `ElementClickInterceptedException` (and `WebDriverException` whose `msg` contains `"is not clickable"`).
- Keep all docstrings consistent with the existing style (Google docstrings).

**NOT in scope**:
- Rewriting `executor.py` (TASK-729).
- Rewriting `snapshot_from_driver` (TASK-730).
- Touching `_PlaywrightSetup` / `_create_selenium_setup` in `driver_context.py` (TASK-728).
- Adding `wait_for_url_contains` / `wait_for_title_contains` to abstract — those are local helpers in TASK-729.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py` | MODIFY | Widen `select_option` signature with `by` keyword |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py` | MODIFY | Dispatch on `by`; add scroll-into-view click fallback |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` | MODIFY | Dispatch on `by` |
| `packages/ai-parrot-tools/tests/scraping/test_drivers.py` (or new `test_abstract_driver_extensions.py`) | CREATE/UPDATE | Unit tests for new behavior |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.drivers.abstract import AbstractDriver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py:11

from parrot_tools.scraping.drivers.selenium_driver import SeleniumDriver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py:20

from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver
# verified: packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py:15

# Selenium internals used inside SeleniumDriver only:
from selenium.webdriver.support.ui import Select
from selenium.common.exceptions import ElementClickInterceptedException, WebDriverException
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py:91
@abstractmethod
async def select_option(
    self, selector: str, value: str, timeout: int = 10
) -> None: ...

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py:148
async def select_option(self, selector: str, value: str, timeout: int = 10) -> None:
    await self._wait_for_element(selector, timeout)
    element = await self._run(self._find_element, selector)
    await self._run(self._select_by_value, element, value)

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py:156
def _select_by_value(self, element: Any, value: str) -> None:
    from selenium.webdriver.support.ui import Select
    Select(element).select_by_value(value)

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py:133
async def click(self, selector: str, timeout: int = 10) -> None:
    await self._wait_for_element(selector, timeout)
    element = await self._run(self._find_element, selector)
    await self._run(element.click)

# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py:112
async def select_option(self, selector: str, value: str, timeout: int = 10) -> None:
    sel = self._resolve_selector(selector)
    await self._page.locator(sel).select_option(value, timeout=timeout * 1000)
```

### Does NOT Exist
- ~~`AbstractDriver.select_option(by="text")`~~ — the `by` kwarg is what THIS task adds
- ~~`SeleniumDriver._select_by_text` / `_select_by_index`~~ — must be created
- ~~Playwright `locator.select_option(text=...)`~~ — Playwright uses `label=`, not `text=`
- ~~`AbstractDriver.click_with_scroll_fallback`~~ — fallback is internal to `SeleniumDriver.click`

---

## Implementation Notes

### Pattern to Follow

```python
# In SeleniumDriver
async def select_option(
    self, selector: str, value: str, *, by: str = "value", timeout: int = 10
) -> None:
    await self._wait_for_element(selector, timeout)
    element = await self._run(self._find_element, selector)
    await self._run(self._select_dispatch, element, value, by)

def _select_dispatch(self, element: Any, value: str, by: str) -> None:
    from selenium.webdriver.support.ui import Select
    sel = Select(element)
    if by == "value":
        sel.select_by_value(value)
    elif by == "text":
        sel.select_by_visible_text(value)
    elif by == "index":
        sel.select_by_index(int(value))
    else:
        raise ValueError(f"Unsupported select 'by' mode: {by!r}")

async def click(self, selector: str, timeout: int = 10) -> None:
    from selenium.common.exceptions import (
        ElementClickInterceptedException,
        WebDriverException,
    )
    await self._wait_for_element(selector, timeout)
    element = await self._run(self._find_element, selector)
    try:
        await self._run(element.click)
    except ElementClickInterceptedException:
        await self._run(self._scroll_into_view_and_click, element)
    except WebDriverException as exc:
        if "is not clickable" in str(exc):
            await self._run(self._scroll_into_view_and_click, element)
        else:
            raise

def _scroll_into_view_and_click(self, element: Any) -> None:
    self._driver.execute_script(
        "arguments[0].scrollIntoView({block:'center'}); arguments[0].click();",
        element,
    )
```

### Key Constraints

- Keep `selector` and `value` positional in `select_option`. The new `by` MUST be keyword-only (use `*,` separator) so existing call sites with two positional args still work.
- Do NOT change abstract method ordering or break `@abstractmethod`.
- Selenium `select_by_index` requires `int`; coerce inside the dispatcher and let `ValueError` propagate naturally if the caller passed a non-numeric string.
- Playwright `select_option(label=...)` is the correct keyword for visible text — not `text=`.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py` — full contract.
- `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py:60-66` — the `_run` executor dispatcher pattern.
- `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py:333-367` — current click-with-fallback logic to mirror inside SeleniumDriver.

---

## Acceptance Criteria

- [ ] `AbstractDriver.select_option(self, selector, value, *, by="value", timeout=10)` — signature confirmed.
- [ ] `SeleniumDriver.select_option(...by="text")` selects by visible text on a real `<select>` (or via mocked `Select`).
- [ ] `SeleniumDriver.select_option(...by="index")` calls `select_by_index(int(value))`.
- [ ] `PlaywrightDriver.select_option(...by="text")` calls `locator.select_option(label=..., timeout=...)`.
- [ ] `PlaywrightDriver.select_option(...by="index")` calls `locator.select_option(index=int(value), timeout=...)`.
- [ ] `SeleniumDriver.click` catches `ElementClickInterceptedException` and retries once via JS `scrollIntoView({block:'center'})` + JS `.click()`.
- [ ] All existing tests in `packages/ai-parrot-tools/tests/scraping/` continue to pass.
- [ ] New unit tests cover the four new code paths above.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/scraping/test_abstract_driver_extensions.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parrot_tools.scraping.drivers.selenium_driver import SeleniumDriver
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver
from parrot_tools.scraping.drivers.playwright_config import PlaywrightConfig


class TestSeleniumSelectOption:
    @pytest.mark.asyncio
    async def test_by_value(self, ...):
        # patch Select; assert select_by_value called with "v"
        ...

    @pytest.mark.asyncio
    async def test_by_text(self, ...):
        # assert select_by_visible_text called with "Foo"
        ...

    @pytest.mark.asyncio
    async def test_by_index(self, ...):
        # assert select_by_index called with 2 (int conversion)
        ...

    @pytest.mark.asyncio
    async def test_unknown_by_raises(self, ...):
        with pytest.raises(ValueError, match="Unsupported select"):
            ...


class TestSeleniumClickFallback:
    @pytest.mark.asyncio
    async def test_intercepted_click_retries_with_js(self, ...):
        # element.click raises ElementClickInterceptedException
        # then driver.execute_script is called with scrollIntoView+click
        ...


class TestPlaywrightSelectOption:
    @pytest.mark.asyncio
    async def test_by_value(self, ...):
        # locator.select_option called with value=v
        ...

    @pytest.mark.asyncio
    async def test_by_label(self, ...):
        # by="text" → locator.select_option called with label=v
        ...

    @pytest.mark.asyncio
    async def test_by_index(self, ...):
        # by="index" → locator.select_option called with index=int(v)
        ...
```

---

## Agent Instructions

1. Read the spec section "Module 2" at `sdd/specs/fix-webscrapingtoolkit-executor.spec.md`.
2. No upstream task dependencies — this is foundational work.
3. Verify the listed signatures with `read` before editing.
4. Implement, test, mark complete, move file to `sdd/tasks/completed/`.

---

## Completion Note

*(Agent fills this in when done)*
