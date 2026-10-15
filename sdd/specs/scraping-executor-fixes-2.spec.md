---
type: feature
base_branch: dev
projects: [ai-parrot-tools]
tags: [scraping, browsing, executor, xpath, ledger-fix]
---

# Feature Specification: Scraping Executor Fixes 2 — XPath escaping, focused clear_first, submit pseudos

**Feature ID**: FEAT-684
**Date**: 2026-10-15
**Author**: agent:sdd-fix (ledger `issue:28c2e9573ce2`)
**Status**: approved
**Target version**: next ai-parrot-tools patch

---

## 1. Motivation & Business Requirements

### Problem Statement

Ledger `issue:28c2e9573ce2` (major bug, discovered from FEAT-681) reports three defects in
`packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`:

1. **Unescaped text-selector XPath.** `_resolve_locator(selector, "text")` and the `text`
   branch of `_action_click` build `f"//*[contains(text(), '{selector}')]"`. Any single quote
   in the (often LLM-supplied) text — `Don't miss`, `O'Reilly` — produces an invalid XPath,
   and a crafted value can inject arbitrary XPath (`') or ('1'='1`).
2. **`type` with `selector=None` ignores `clear_first`.** All three drivers
   (`PlaywrightDriver`, `PageDriver`, `SeleniumDriver`) only clear when a selector is given;
   with `selector=None` the text is appended to whatever the focused element already holds,
   silently contradicting the plan.
3. **`submit` passes BeautifulSoup-only pseudos to the browser.** `_action_submit` embeds the
   raw selector into `document.querySelector(...)` and then `driver.click(selector)`. A
   selector carrying `:contains(...)` / `:-soup-contains(...)` / `:has(...)` (allowed by the
   plan generator for extraction) throws a `SyntaxError` in `querySelector`. `click`, `hover`
   and `wait` already strip these via `_strip_soup_only_pseudos`.

### Goals
- Text selectors produce a valid, injection-safe XPath for any input string.
- `type(selector=None, clear_first=True)` clears the focused element before typing, on every driver.
- `submit` strips BS4-only pseudos from CSS selectors (target and `wait_after_submit`) the
  same way `click`/`hover`/`wait` do; XPath selectors are untouched.

### Non-Goals (explicitly out of scope)
- The legacy `WebScrapingTool` in `parrot_tools/scraping/tool.py` (same f-string pattern,
  separate code path) — not referenced by the issue.
- Driver changes (`drivers/*.py`): the fix lives in the executor so it is uniform across drivers.
- Text-contains matching for `submit` (a JS text filter like `_action_click`'s) — stripping only.

---

## 2. Architectural Design

### Overview
All three fixes are local to `executor.py`:
- New private helper `_xpath_literal(value: str) -> str` returns an XPath 1.0 string literal
  (`'v'`, `"v"`, or `concat('a', "'", 'b')` when both quote kinds occur). `_resolve_locator`
  and `_action_click`'s text branch use it.
- `_action_type`: when `selector is None and clear_first`, run one `driver.evaluate` IIFE that
  clears `document.activeElement` (`value` for inputs/textareas, `textContent` for
  contenteditable) and dispatches a bubbling `input` event, then call `driver.type_text` as today.
- `_action_submit`: for a non-XPath selector, apply `_strip_soup_only_pseudos`; raise
  `RuntimeError` if it reduces to empty. Same for `wait_after_submit`.

### Integration Points
- `driver.evaluate(expression)` — the uniform JS entry point (Selenium prefixes `return `,
  Playwright/Page evaluate the bare expression). The IIFE must not start with whitespace/newline.

### Data Models
None changed.

### New Public Interfaces
None (private helper only).

---

## 3. Module Breakdown

### Module 1: executor fixes (`executor.py`)
`_xpath_literal`, `_resolve_locator`, `_action_click` (text branch), `_action_type`,
`_action_submit`. One task.

---

## 4. Test Specification

### Unit Tests (`packages/ai-parrot-tools/tests/scraping/test_executor_action_gaps.py`)
- `_xpath_literal` for plain, single-quote, double-quote and mixed-quote inputs.
- hover/click with `selector_type="text"` and a `'` in the text → `concat(...)`-based locator.
- `type` with `selector=None, clear_first=True` → `evaluate` awaited (activeElement clear)
  before `type_text`; with `clear_first=False` → no evaluate.
- `submit` with `form:has(button)` / `button:-soup-contains('Go')` → evaluate expression and
  click use the stripped selector; selector reducing to empty raises and is recorded as a
  step error; XPath selectors unchanged; `wait_after_submit` stripped.

---

## 5. Acceptance Criteria
- [ ] No f-string interpolation of user text into an XPath literal remains in `executor.py`.
- [ ] `_xpath_literal` output is a valid XPath literal for inputs containing `'`, `"`, or both.
- [ ] `type(selector=None, clear_first=True)` clears the focused element via `driver.evaluate`.
- [ ] `submit` never forwards `:contains`/`:-soup-contains`/`:has` to the browser.
- [ ] Existing scraping executor tests pass; `ruff check` clean.

---

## 6. Codebase Contract

### Verified Imports
```python
import json  # executor.py (already used by _action_click/_action_submit)
from parrot_tools.scraping.executor import execute_plan_steps  # tests/scraping/test_executor_action_gaps.py:8
from parrot_tools.scraping.plan import ScrapingPlan  # tests/scraping/test_executor_action_gaps.py:9
```

### Existing Signatures
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py
async def _action_click(driver, action, default_timeout) -> bool  # text branch ~line 530
async def _action_type(driver, action, default_timeout) -> bool  # ~line 550
def _resolve_locator(selector: str, selector_type: str = "css") -> str  # ~line 565
async def _action_submit(driver, action, default_timeout) -> bool  # ~line 582
def _strip_soup_only_pseudos(selector: str) -> str  # ~line 1100
# drivers/abstract.py
async def type_text(self, text, selector=None, delay_ms=0, clear_first=False, timeout=10) -> None
async def evaluate(self, expression: str) -> Any
# models.py: Submit(selector: str, wait_after_submit: Optional[str], wait_timeout: int) — no selector_type
```

### Does NOT Exist
- ~~`Submit.selector_type`~~ — submit detects XPath by a leading `/` or `./`.
- ~~`AbstractDriver.clear()`~~ / ~~`AbstractDriver.focused_element()`~~ — no such driver methods.
