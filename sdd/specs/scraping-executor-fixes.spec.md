---
type: feature
base_branch: dev
projects: [ai-parrot-tools]
tags: [scraping, browsing, executor, playwright, ledger-fix]
---

# Feature Specification: Scraping Executor Fixes — click text-contains under Playwright

**Feature ID**: FEAT-682
**Date**: 2026-10-15
**Author**: agent:sdd-fix (ledger `issue:c10c1e94f4b3`)
**Status**: approved
**Target version**: next ai-parrot-tools patch

---

## 1. Motivation & Business Requirements

### Problem Statement

`_action_click` (`packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py:449`)
handles a CSS selector carrying a text-contains pseudo-class
(`button:-soup-contains('Next')`, `a:contains("More")`) by running a JS snippet that
reads `arguments[0]` (the CSS prefix) and `arguments[1]` (the needle), and calls
`driver.execute_script(script, selector, js_text_filter)`.

`arguments[N]` is a Selenium `execute_script` convention. `PlaywrightDriver` and
`PageDriver` implement `execute_script(script, *args)` as
`self._page.evaluate(script, *args)`; Playwright's `page.evaluate` accepts **one**
optional `arg` and never binds `arguments`. Under those drivers the text-contains
click either raises (`TypeError` for the extra positional argument) or evaluates
`arguments` as undefined — the click never happens. Selenium works by accident.

Discovered while specifying FEAT-681 (`browsing-executor-action-gaps`), which
explicitly excluded it and filed it in the ledger.

### Goals
- The text-contains click path works identically on Selenium, Playwright and Page drivers.
- The JS runs through the driver-neutral `driver.evaluate(expression)` as a self-contained
  IIFE with the CSS prefix and needle embedded via `json.dumps` (no `arguments`, no
  extra positional args) — the same pattern FEAT-681 mandates for `_action_submit`.
- Behaviour on a match / no match is unchanged: dispatch a bubbling `MouseEvent('click')`
  on the first element whose `textContent` contains the needle (case-insensitive),
  return `True`; raise `RuntimeError` when none matches.

### Non-Goals (explicitly out of scope)
- The non-text paths of `_action_click` (`driver.click(locator, timeout)`) — unchanged.
- Quote-escaping in the `selector_type == "text"` XPath builder.
- Other `execute_script` call sites in the executor (`_action_scroll`, `_action_evaluate`,
  `_action_refresh`). The `scroll: bottom` height script's leading `return` has its own
  ledger issue.
- Any FEAT-681 action (`hover`, `type`, `submit`, `screenshot`).

---

## 2. Architectural Design

### Overview
Replace the `execute_script(script, selector, js_text_filter)` call with
`driver.evaluate(expr)`, where `expr` is an immediately-invoked arrow function whose
literals are produced by `json.dumps(selector)` and `json.dumps(js_text_filter.lower())`.
`evaluate` is abstract on `AbstractDriver` and implemented by every driver:
Playwright/Page → `page.evaluate(expression)`; Selenium → `execute_script("return " + expression)`.
An IIFE expression is valid in both forms and returns its boolean.

### Component Diagram
```
_dispatch_step ──→ _action_click ──┬─ text-contains ─→ driver.evaluate("(() => {...})()")   (changed)
                                   └─ otherwise ─────→ driver.click(locator, timeout)        (unchanged)
```

### Integration Points
| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractDriver.evaluate` | uses | abstract, `drivers/abstract.py:220` |
| `PlaywrightDriver.evaluate` / `PageDriver.evaluate` | uses | `page.evaluate(expression)` |
| `SeleniumDriver.evaluate` | uses | `execute_script(f"return {expression}")` |

### Data Models
None.

### New Public Interfaces
None — `_action_click` keeps its signature.

---

## 3. Module Breakdown

#### Delegation-eligible modules
| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: click text-contains via evaluate | yes | IIFE + `json.dumps` literals, `driver.evaluate`, same RuntimeError | — |

### Module 1: click text-contains via `driver.evaluate`
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py`
- **Responsibility**: Build the text-contains click as a self-contained expression and run it with `driver.evaluate`.
- **Depends on**: existing `AbstractDriver.evaluate`
- **Interface Skeleton**:
  ```python
  # modifies executor.py:449 (signature unchanged)
  async def _action_click(driver: AbstractDriver, action: Any, default_timeout: int) -> bool:
      """Click an element.

      Text-contains CSS selectors run as one ``driver.evaluate`` IIFE with the CSS prefix
      and needle embedded via ``json.dumps`` (never as script arguments), so the path is
      driver-neutral. Raises RuntimeError when no element contains the text.
      """
  ```

---

## 4. Test Specification

### Unit Tests (`packages/ai-parrot-tools/tests/scraping/test_executor.py`)
| Test | Module | Description |
|---|---|---|
| `test_click_text_contains_uses_evaluate` | M1 | `button:-soup-contains('Next')` → `driver.evaluate` called once with an expression containing `json.dumps("button")` and `json.dumps("next")`; `driver.execute_script` and `driver.click` not called |
| `test_click_text_contains_no_arguments_binding` | M1 | the evaluated expression contains no `arguments[` |
| `test_click_text_contains_quotes_escaped` | M1 | prefix `a[title="x"]` → the JSON-escaped literal appears verbatim; expression stays one string |
| `test_click_text_contains_miss_raises` | M1 | `evaluate` returns `False` → step recorded as failed (RuntimeError surfaced via `step_errors` / failure), no `driver.click` |
| `test_click_plain_selector_unchanged` | M1 | `#btn` → `driver.click("#btn", timeout)`; `evaluate` not called |

---

## 5. Acceptance Criteria
- [ ] Text-contains click calls `driver.evaluate` exactly once and never `driver.execute_script`.
- [ ] Selector and needle are embedded with `json.dumps`; the expression contains no `arguments[`.
- [ ] Miss → `RuntimeError` (same message shape as before); hit → `True`.
- [ ] Plain CSS / XPath / text paths unchanged; existing `tests/scraping/` tests still pass.
- [ ] `ruff check` clean on the touched files.

---

## 6. Codebase Contract

### Verified Imports
```python
import json  # verified: executor.py:15 (already imported)
```

### Existing Class Signatures
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py
class AbstractDriver:
    async def execute_script(self, script: str, *args: Any) -> Any:  # line 208
    async def evaluate(self, expression: str) -> Any:  # line 220 (abstract)
# drivers/playwright_driver.py:269 / drivers/page_driver.py:177 → self._page.evaluate(expression)
# drivers/selenium_driver.py:368 → execute_script(f"return {expression}")
# executor.py
async def _action_click(driver: AbstractDriver, action: Any, default_timeout: int) -> bool:  # line 449
_SOUP_CONTAINS_TEXT_RE  # line 948
def _strip_soup_only_pseudos(selector: str) -> str:  # line 954
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| text-contains click | `AbstractDriver.evaluate` | method call | `drivers/abstract.py:220` |

### Does NOT Exist (Anti-Hallucination)
- ~~`AbstractDriver.evaluate(expression, *args)`~~ — `evaluate` takes the expression only.
- ~~`driver.click_text(...)`~~ — no such driver method.

### Edit Sites (Blueprint Anchors)
Verified against: `3d2e813c4`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | MODIFY | `hit = await driver.execute_script(script, selector, js_text_filter)` | `executor.py:503` | 1 |
| `packages/ai-parrot-tools/tests/scraping/test_executor.py` | MODIFY | `def mock_driver():` | `test_executor.py:26` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Same embedding rule as FEAT-681 §7 (`_action_submit`): values go into the JS via
  `json.dumps`, never as script arguments.
- Lower-case the needle in Python before embedding (the JS compares against
  `textContent.toLowerCase()`).

### Known Risks / Gotchas
- FEAT-681 edits other functions in the same file concurrently; keep the diff confined
  to the text-contains block of `_action_click` to avoid merge conflicts.
- A JSON string literal is a valid JS string literal, so `json.dumps` output is safe to
  splice into the expression (including quotes, backslashes and non-ASCII).

### External Dependencies
None.

---

## 8. Open Questions
None.

---

## Revision History
| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-15 | agent:sdd-fix | Initial spec from ledger issue:c10c1e94f4b3 |
