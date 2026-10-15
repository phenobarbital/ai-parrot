---
type: feature
base_branch: dev
feature_id: FEAT-686
projects: [ai-parrot-tools]
tags: [scraping, playwright, obscura, cdp]
---

# Feature Specification: Obscura-safe load waits and page reads in `PlaywrightDriver`

**Feature ID**: FEAT-686
**Date**: 2026-10-15
**Author**: Jesus Lara (sdd-fix lane)
**Status**: approved
**Target version**: next

Resolves ledger issue:b09cc5d3389d (discovered from issue:d06fedf43c45).

---

## 1. Motivation & Business Requirements

### Problem Statement
The three real-Obscura tests in `test_fixture_site_integration.py`
(`TestObscuraPlaywrightFixtureSite`, `TestObscuraScrapingPlanDriverParity`,
`TestObscuraBrowsingToolkitCatalogFlow`) fail on `dev` with Obscura 0.2.2.

Reproduced against the real binary (2026-10-15). After a **renderer-initiated**
navigation (a form submit via `click()`; a `goto()` is unaffected):

1. Obscura never emits the `domcontentloaded` / `load` lifecycle events, so
   `page.wait_for_load_state("load" | "domcontentloaded")` always times out,
   even though `document.readyState == "complete"`. `networkidle` does fire.
2. Playwright's **utility world** is broken for the new document: the first
   utility-world call (`page.content()`, `locator.inner_text()`,
   `page.wait_for_selector()`) fails with
   `TypeError: Cannot read properties of undefined (reading 'evaluate')`, and
   every later one with `utilityScript.evaluate is not a function` /
   `injected.eval is not a function`, until the next `goto()`.
3. The **main world** keeps working: `page.evaluate(...)` returns the new
   document's state, `page.screenshot()` works.

The issue's candidate fix (fall back to `page.evaluate(outerHTML)`) is correct
for page reads; it is not sufficient on its own because of (1).

### Goals
- In `engine == "obscura"` mode only, `wait_for_load_state("load" |
  "domcontentloaded")` and `wait_for_navigation()` poll `document.readyState`
  through main-world `page.evaluate` instead of waiting on lifecycle events.
- In `engine == "obscura"` mode only, `get_page_source()` and `get_text()`
  fall back to a main-world `page.evaluate` read when the Playwright call fails
  with a non-timeout error.
- The default `engine == "playwright"` path is unchanged byte for byte.

### Non-Goals
- Fixing locator-based actions (`fill`/`click`/`wait_for_selector`) on a
  document reached by a renderer-initiated navigation — an Obscura upstream
  defect; no driver-side workaround without re-requesting the page.
- `DriverRegistry` "obscura" entry (separate known gap).

---

## 2. Architectural Design

All changes are private to `PlaywrightDriver`; callers (`executor.py`,
`session_actions.py`, `WebBrowsingToolkit`) need no Obscura branching.

- `_is_obscura` property: `self.config.engine == "obscura"`.
- `_poll_ready_state(state, timeout)`: polls `document.readyState` every 100 ms
  (`"domcontentloaded"` → `interactive`/`complete`, `"load"` → `complete`),
  tolerating transient evaluate errors mid-navigation; raises `TimeoutError`
  when the deadline passes. Other states (`networkidle`, `commit`) still go to
  Playwright.
- `get_page_source()` fallback: doctype + `document.documentElement.outerHTML`.
- `get_text()` fallback: main-world `innerText` of the first element matching
  the CSS or `xpath=` selector (as resolved by `_resolve_selector`); `None`
  match raises.

---

## 3. Module Breakdown

### Module 1: Obscura branches in `PlaywrightDriver`
- `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py`
- Unit tests (mocked page) in `packages/ai-parrot-tools/tests/scraping/test_playwright_driver.py`.

---

## 4. Test Specification
- Mocked: obscura `wait_for_load_state("load")` polls `evaluate` until
  `complete` and never calls `page.wait_for_load_state`; `"networkidle"` still
  delegates; times out with `TimeoutError`; `wait_for_navigation` polls.
- Mocked: obscura `get_page_source()` falls back to `evaluate` when `content()`
  raises; `get_text()` falls back when `inner_text` raises; a timeout error is
  re-raised, not masked.
- Mocked: playwright engine still calls `page.wait_for_load_state` / `content()`.
- Real (opt-in, Obscura on PATH): the three `TestObscura*` integration tests pass.

---

## 5. Acceptance Criteria
- [ ] `pytest packages/ai-parrot-tools/tests/scraping/test_playwright_driver.py` passes.
- [ ] With `obscura` 0.2.2 on PATH, `pytest packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py -k Obscura` passes (3 tests).
- [ ] Default-engine behaviour unchanged (existing waiting/content tests untouched and green).
- [ ] `ruff check` clean on touched files.

---

## 6. Codebase Contract

### Verified Imports
- `from .abstract import AbstractDriver` / `from .playwright_config import PlaywrightConfig` (playwright_driver.py:11-12)

### Existing Class Signatures
- `PlaywrightDriver.get_page_source(self) -> str` — playwright_driver.py:222
- `PlaywrightDriver.get_text(self, selector: str, timeout: int = 10) -> str` — :226
- `PlaywrightDriver.wait_for_navigation(self, timeout: int = 30) -> None` — :278
- `PlaywrightDriver.wait_for_load_state(self, state: str = "load", timeout: int = 30) -> None` — :282
- `PlaywrightDriver._resolve_selector(self, selector: str) -> str` — :479 (returns `xpath=<expr>` for XPath)
- `PlaywrightConfig.engine: str = "playwright"` — playwright_config.py:101

### Does NOT Exist
- No `_is_obscura` / `_poll_ready_state` helpers before this feature.
- The module does not import `playwright` at top level (lazy import in `start()`), so error types are matched by name.

---

## 7. Implementation Notes & Constraints
- Never call `page.content()` again just to "test" the utility world — a failing
  utility call is what poisons it.
- Keep the module's lazy-import property (no top-level `playwright` import).

## 8. Open Questions
None.

## Revision History
- 2026-10-15: initial (sdd-fix lane for issue:b09cc5d3389d).
