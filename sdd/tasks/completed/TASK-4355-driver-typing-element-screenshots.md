# TASK-4355: Add driver typing and element screenshot capabilities

**Feature**: FEAT-681 - Browsing Executor Action Gaps
**Spec**: `sdd/specs/browsing-executor-action-gaps.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement the assigned portion of approved FEAT-681 §§2–7. Browsing replays saved actions through the standalone executor; model validation currently accepts actions that execution does not fully support.

## Scope

Implement spec M1 and its unit tests. Add the two concrete base defaults and implementations in all three backends. Preserve screenshot signatures and Selenium viewport semantics.

**NOT in scope**: legacy `scraping/tool.py`, `_action_click` repairs (ledger issue:c10c1e94f4b3), new dependencies, model changes, Selenium full-page emulation, or public executor signature changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py` | MODIFY | Add optional driver capability implementations |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` | MODIFY | Add optional driver capability implementations |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/page_driver.py` | MODIFY | Add optional driver capability implementations |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py` | MODIFY | Add optional driver capability implementations |
| `packages/ai-parrot-tools/tests/scraping/test_driver_type_and_element_screenshot.py` | CREATE | Backend capability tests |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import pytest
import asyncio
from parrot_tools.scraping.drivers.abstract import AbstractDriver
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver
from parrot_tools.scraping.drivers.page_driver import PageDriver
from parrot_tools.scraping.drivers.selenium_driver import SeleniumDriver
```

Imports verified against the named source modules; stdlib imports are built-in. pytest is already used in the neighboring regression tests. Playwright and Selenium are existing scraping extras in packages/ai-parrot-tools/pyproject.toml:73. Relative imports in modified modules retain their existing spelling.

### Existing Signatures to Use

- `drivers/abstract.py:163`: `screenshot(self, path: str, full_page: bool = False) -> bytes` is abstract; optional capabilities below use concrete methods raising NotImplementedError.
- `drivers/playwright_driver.py:29,244,456`: constructor accepts optional config; `_page` backs screenshot; `_resolve_selector(self, selector: str) -> str` prefixes `/` and `./` as XPath.
- `drivers/page_driver.py:27,34,147`: constructor takes `page: Any`; static `_resolve_selector(selector: str) -> str`; screenshot delegates to wrapped page.
- `drivers/selenium_driver.py:61,117,284`: async `_run(self, func: Any, *args: Any, **kwargs: Any) -> Any`; blocking `_find_element(self, selector: str) -> Any`; async `_wait_for_element(self, selector: str, timeout: int = 10) -> None`.
- `drivers/selenium_driver.py:273`: screenshot returns viewport PNG, ignoring full_page today.

Exact existing symbol references:
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py#AbstractDriver`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py#PlaywrightDriver`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/page_driver.py#PageDriver`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py#SeleniumDriver`

### Does NOT Exist

- `AbstractDriver.type_text` and `screenshot_element` do not yet exist; this task creates them.
- `AbstractDriver.submit` does not exist and must not be added.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/page_driver.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/scraping/test_driver_type_and_element_screenshot.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py#AbstractDriver",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py#PlaywrightDriver",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/page_driver.py#PageDriver",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py#SeleniumDriver"
  ]
}
```

## Implementation Notes

Independent driver files and a new test module; no executor writes or shared-state mutations.
Use async I/O, existing logging, Google docstrings and strict type hints. Format touched Python with black (120 columns) and run ruff check. Store validation logs in artifacts/logs/. Do not leave blueprint placeholders in implementation files.

## Implementation Blueprint

### Steps (in order)

1. Add base defaults — concrete optional methods preserve existing subclass instantiation.
2. Implement Playwright and Page adapters — reuse selector resolution and seconds-to-ms conversion.
3. Implement Selenium and its full-page debug notice — bridge blocking property access and disk writes as well as method calls.
4. Add mocked backend tests — prove semantics without installing browsers.

### `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py` (MODIFY)
```python
# Anchor:     async def screenshot(self, path: str, full_page: bool = False) -> bytes:
# occurrences: 1 (verified with grep -F -c; packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py:163)
# Insert AFTER the complete screenshot method, before the next decorator.
# Both new methods are concrete: raise NotImplementedError with a capability message.
# Do not decorate either method with abstractmethod.
    async def type_text(
        self, text: str, selector: Optional[str] = None, delay_ms: int = 0,
        clear_first: bool = False, timeout: int = 10,
    ) -> None:
        """Type keystrokes; optionally select and clear a target, with delay in milliseconds."""
        # FILL IN: implement the backend rules in AC-1 through AC-4.

    async def screenshot_element(self, selector: str, path: str, timeout: int = 10) -> bytes:
        """Save an element PNG to path and return its raw bytes; timeout is seconds."""
        # FILL IN: implement capture and return bytes, bounded by AC-1 through AC-4.
```
**Why**: Extend the existing driver boundary without breaking third-party subclasses or blocking the event loop.

### `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` (MODIFY)
```python
# Anchor:     async def screenshot(self, path: str, full_page: bool = False) -> bytes:
# occurrences: 1 (verified with grep -F -c; packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py:244)
# Insert AFTER the complete screenshot method.
# Resolve selector with self._resolve_selector; locator.fill("") only when selected and clear_first.
# Then locator.press_sequentially(text, delay=delay_ms, timeout=timeout * 1000).
# No selector: self._page.keyboard.type(text, delay=delay_ms); do not clear focused input.
# Screenshot: locator.screenshot(path=path, timeout=timeout * 1000).
    async def type_text(
        self, text: str, selector: Optional[str] = None, delay_ms: int = 0,
        clear_first: bool = False, timeout: int = 10,
    ) -> None:
        """Type keystrokes; optionally select and clear a target, with delay in milliseconds."""
        # FILL IN: implement the backend rules in AC-1 through AC-4.

    async def screenshot_element(self, selector: str, path: str, timeout: int = 10) -> bytes:
        """Save an element PNG to path and return its raw bytes; timeout is seconds."""
        # FILL IN: implement capture and return bytes, bounded by AC-1 through AC-4.
```
**Why**: Extend the existing driver boundary without breaking third-party subclasses or blocking the event loop.

### `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/page_driver.py` (MODIFY)
```python
# Anchor:     async def screenshot(self, path: str, full_page: bool = False) -> bytes:
# occurrences: 1 (verified with grep -F -c; packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/page_driver.py:147)
# Insert AFTER the complete screenshot method.
# Mirror PlaywrightDriver using this adapter's own self._resolve_selector and self._page.
# Selected: optional fill("") then press_sequentially with ms timeout and delay.
# Focused: keyboard.type; screenshot: locator.screenshot returning bytes.
    async def type_text(
        self, text: str, selector: Optional[str] = None, delay_ms: int = 0,
        clear_first: bool = False, timeout: int = 10,
    ) -> None:
        """Type keystrokes; optionally select and clear a target, with delay in milliseconds."""
        # FILL IN: implement the backend rules in AC-1 through AC-4.

    async def screenshot_element(self, selector: str, path: str, timeout: int = 10) -> bytes:
        """Save an element PNG to path and return its raw bytes; timeout is seconds."""
        # FILL IN: implement capture and return bytes, bounded by AC-1 through AC-4.
```
**Why**: Extend the existing driver boundary without breaking third-party subclasses or blocking the event loop.

### `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py` (MODIFY)
```python
# Anchor:     async def screenshot(
# occurrences: 1 (verified with grep -F -c; packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py:273)
# Insert AFTER the complete screenshot method; add full_page debug logging inside that method.
# Selected: await _wait_for_element then await _run(_find_element, selector).
# Focused: access switch_to.active_element INSIDE _run, not on the event loop.
# Clear only if selector and clear_first. Run all send_keys calls via _run.
# Positive delay: per-character keys and asyncio.sleep(delay_ms / 1000) BETWEEN keys.
# Zero delay: one send_keys(text). PNG property access and Path.write_bytes run via _run.
    async def type_text(
        self, text: str, selector: Optional[str] = None, delay_ms: int = 0,
        clear_first: bool = False, timeout: int = 10,
    ) -> None:
        """Type keystrokes; optionally select and clear a target, with delay in milliseconds."""
        # FILL IN: implement the backend rules in AC-1 through AC-4.

    async def screenshot_element(self, selector: str, path: str, timeout: int = 10) -> bytes:
        """Save an element PNG to path and return its raw bytes; timeout is seconds."""
        # FILL IN: implement capture and return bytes, bounded by AC-1 through AC-4.
```
**Why**: Extend the existing driver boundary without breaking third-party subclasses or blocking the event loop.

### `packages/ai-parrot-tools/tests/scraping/test_driver_type_and_element_screenshot.py` (CREATE)
```python
"""Typing and element screenshot contract tests across browser backends."""
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import pytest
import asyncio
from parrot_tools.scraping.drivers.abstract import AbstractDriver
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver
from parrot_tools.scraping.drivers.page_driver import PageDriver
from parrot_tools.scraping.drivers.selenium_driver import SeleniumDriver

@pytest.mark.parametrize("driver_class", [PlaywrightDriver, PageDriver])
async def test_playwright_type_text_with_selector(driver_class: Any) -> None:
    """Both Playwright adapters clear and type with converted timeout."""
    # FILL IN: use MagicMock for locator(), AsyncMock for locator methods; AC-2.

async def test_abstract_driver_defaults_raise() -> None:
    """An old concrete subclass still instantiates and rejects optional capabilities."""
    # FILL IN: implement minimal abstract methods locally; do not patch __abstractmethods__.

async def test_selenium_type_text_and_screenshot_element(tmp_path: Path) -> None:
    """Selenium returns the bytes written and bridges all blocking operations."""
    # FILL IN: fake WebDriver and spy bridge; cover AC-3 and add focused/delay tests.
# FILL IN: add focused typing, CSS/XPath screenshots, error propagation and PageDriver cases.
```
**Why**: Mock both Playwright adapters and Selenium so unit coverage needs no installed browser.

### FILL IN checklist

- [ ] Complete packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py according to its bounded blueprint and AC below.
- [ ] Complete packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py according to its bounded blueprint and AC below.
- [ ] Complete packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/page_driver.py according to its bounded blueprint and AC below.
- [ ] Complete packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/selenium_driver.py according to its bounded blueprint and AC below.
- [ ] Complete packages/ai-parrot-tools/tests/scraping/test_driver_type_and_element_screenshot.py according to its bounded blueprint and AC below.

## Acceptance Criteria

- [ ] AC-1: Base methods have the exact spec signatures, are non-abstract and raise NotImplementedError.
- [ ] AC-2: Playwright and Page use sequential typing, focused keyboard typing, optional selected clearing, CSS/XPath resolution and millisecond timeouts; return locator screenshot bytes.
- [ ] AC-3: Selenium supports selected/focused typing, delay conversion and per-character pacing; all WebDriver and file operations use _run. Element PNG bytes equal disk bytes.
- [ ] AC-4: clear_first without selector does not clear focused input; Selenium full_page=True remains viewport-only with debug logging.
- [ ] AC-5: Existing driver/parity tests and new tests pass; no new dependencies.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/scraping/test_driver_type_and_element_screenshot.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_abstract_driver.py packages/ai-parrot-tools/tests/scraping/test_playwright_driver.py packages/ai-parrot-tools/tests/scraping/test_selenium_driver.py packages/ai-parrot-tools/tests/scraping/test_executor_driver_parity.py -q`

## Test Specification

Cover every M1 row in spec §4. Parameterize Playwright-style tests over both adapters. Test delay=0, positive delay without a trailing sleep, clear/no-clear, focused typing, CSS/XPath and exception propagation. Assert old concrete subclasses instantiate without overriding the new methods.

## Agent Instructions

1. Use `$sdd-start TASK-4355` to provision the feature worktree; do not implement on dev.
2. Read the spec and verify dependencies are done in `sdd/tasks/index/browsing-executor-action-gaps.json`.
3. Reverify anchors and imports after dependencies land, then complete the blueprint within declared files.
4. Run Validation Commands, black and ruff; record evidence and commit only scoped files.
5. Finalize with `scripts.sdd.finalize_task` and real `TaskCompletionEvidence` for the implementation HEAD (Codex adaptation); do not manually move tasks or use legacy close_task.sh.

## Completion Note


- Task: TASK-4355
- Feature: browsing-executor-action-gaps
- Implementation SHA: cda336c2c368d977beaa554d6e92debd8c6f1191
- Closed at (UTC): 2026-10-15T17:19:47+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 130.6s · Tokens: n/a |
| validation_note | Merge-tier run exit 1: 15 failures identical to origin/dev baseline (chromedriver read-only FS, obscura/playwright env, legacy MagicMock-await toolkit tests); no new test failed. |
