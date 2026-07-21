---
type: Wiki Overview
title: 'TASK-1450: Implement PageDriver adapter for Playwright Page'
id: doc:sdd-tasks-completed-task-1450-page-driver-adapter-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Playwright Pages (from different BrowserContexts) to the executor. `PageDriver`
  bridges
relates_to:
- concept: mod:parrot_tools.scraping.drivers.abstract
  rel: mentions
- concept: mod:parrot_tools.scraping.drivers.page_driver
  rel: mentions
---

# TASK-1450: Implement PageDriver adapter for Playwright Page

**Feature**: FEAT-222 — ScrapingFlow: Composable Long-Horizon Scraping
**Spec**: `sdd/specs/scrapingflow-composable-scraping.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`execute_plan_steps` requires an `AbstractDriver`. FlowExecutor needs to pass individual
Playwright Pages (from different BrowserContexts) to the executor. `PageDriver` bridges
this gap — a lightweight AbstractDriver wrapping a Playwright Page.

Implements spec §Module 6 (PageDriver adapter).

---

## Scope

- Create `PageDriver(AbstractDriver)` implementing all 19 abstract methods
- Each method delegates to the corresponding Playwright Page API
- `start()` → no-op; `quit()` → `page.close()`
- XPath detection: selectors starting with `/` or `./` get `xpath=` prefix
- Write unit tests with mocked Playwright Page

**NOT in scope**: SessionManager (TASK-1451), FlowExecutor (TASK-1452)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/page_driver.py` | CREATE | PageDriver implementation |
| `packages/ai-parrot-tools/tests/scraping/test_page_driver.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.drivers.abstract import AbstractDriver  # drivers/abstract.py:11
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py — ALL 19 abstract methods:
class AbstractDriver(ABC):  # line 11
    async def start(self) -> None: ...          # line 36
    async def quit(self) -> None: ...           # line 39
    async def navigate(self, url: str, timeout: int = 30) -> None: ...  # line 46
    async def go_back(self) -> None: ...        # line 55
    async def go_forward(self) -> None: ...     # line 58
    async def reload(self) -> None: ...         # line 62
    async def click(self, selector: str, timeout: int = 10) -> None: ...  # line 69
    async def fill(self, selector: str, value: str, timeout: int = 10) -> None: ...  # line 78
    async def select_option(self, selector: str, value: str, *, by: str = "value", timeout: int = 10) -> None: ...  # line 89
    async def hover(self, selector: str, timeout: int = 10) -> None: ...  # line 104
    async def press_key(self, key: str) -> None: ...  # line 115
    async def get_page_source(self) -> str: ...  # line 129
    async def get_text(self, selector: str, timeout: int = 10) -> str: ...  # line 140
    async def get_attribute(self, selector: str, attribute: str, timeout: int = 10) -> Optional[str]: ...  # line 151
    async def get_all_texts(self, selector: str, timeout: int = 10) -> List[str]: ...  # line 165
    async def screenshot(self, path: str, full_page: bool = False) -> None: ...  # line 176
    async def wait_for_selector(self, selector: str, timeout: int = 10, state: str = "visible") -> None: ...  # line 184
    async def wait_for_navigation(self, timeout: int = 30) -> None: ...  # line 198
    async def wait_for_load_state(self, state: str = "load", timeout: int = 30) -> None: ...  # line 207
    async def execute_script(self, script: str, *args) -> Any: ...  # line 219
    async def evaluate(self, expression: str) -> Any: ...  # line 233
    @property
    def current_url(self) -> str: ...  # line 244

# Reference implementation for XPath detection (same pattern):
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py
# Lines 351-365: selectors starting with "/" or "./" get "xpath=" prefix
```

### Does NOT Exist
- ~~`parrot_tools.scraping.drivers.page_driver`~~ — this is what you're creating
- ~~`AbstractDriver.new_page()`~~ — not in the abstract interface
- ~~`AbstractDriver.get_context()`~~ — not in the abstract interface

---

## Implementation Notes

### Playwright Page API mapping
```python
# navigate → page.goto(url, timeout=timeout*1000)  # Playwright uses ms
# click → page.click(selector, timeout=timeout*1000)
# fill → page.fill(selector, value, timeout=timeout*1000)
# get_page_source → page.content()
# current_url → page.url
# execute_script → page.evaluate(script, *args)
# evaluate → page.evaluate(expression)
# screenshot → page.screenshot(path=path, full_page=full_page)
# wait_for_selector → page.wait_for_selector(selector, timeout=timeout*1000, state=state)
# wait_for_navigation → page.wait_for_load_state("networkidle", timeout=timeout*1000)
# wait_for_load_state → page.wait_for_load_state(state, timeout=timeout*1000)
# go_back → page.go_back()
# reload → page.reload()
# hover → page.hover(selector, timeout=timeout*1000)
# press_key → page.keyboard.press(key)
# select_option → page.select_option(selector, value=value) or label=value based on by
# get_text → page.inner_text(selector, timeout=timeout*1000)
# get_attribute → page.get_attribute(selector, attribute, timeout=timeout*1000)
# get_all_texts → page.eval_on_selector_all(selector, "els => els.map(e => e.innerText)")
```

### Key Constraints
- Playwright uses milliseconds; AbstractDriver uses seconds — multiply by 1000
- start() is a no-op (page already alive when passed)
- quit() closes the page only (NOT the context or browser)

---

## Acceptance Criteria

- [ ] All 19 AbstractDriver methods implemented and delegating to Page
- [ ] XPath selectors correctly prefixed with `xpath=`
- [ ] Timeout conversion (seconds → milliseconds) correct
- [ ] `start()` is a no-op
- [ ] `quit()` closes the page
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_page_driver.py -v`

---

## Completion Note

Created `drivers/page_driver.py` with `PageDriver(AbstractDriver)` wrapping a
single live Playwright `Page`. All 21 abstract members (19 methods + 2 lifecycle
+ `current_url` property) are implemented, delegating to the page API per the
task's mapping, converting seconds→milliseconds (`timeout * 1000`).

- `start()` is a no-op (page already alive); `quit()` closes only the page
  (`await page.close()`), never the context/browser.
- `_resolve_selector` prefixes selectors starting with `/` or `./` with
  `xpath=` (same logic as PlaywrightDriver).
- `get_all_texts` uses `page.eval_on_selector_all(sel, "els => els.map(e =>
  e.innerText)")`; `select_option` maps by=value/text(label)/index and raises
  ValueError on an unknown mode.

28 unit tests pass against a mocked Page; `isinstance(driver, AbstractDriver)`
confirmed (class is concrete/instantiable). ruff clean.
