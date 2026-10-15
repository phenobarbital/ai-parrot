# TASK-4358: Run the click text-contains path through `driver.evaluate`

**Feature**: FEAT-682 — Scraping Executor Fixes
**Spec**: `sdd/specs/scraping-executor-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned
**discovered_from**: issue:c10c1e94f4b3

---

## Context

Ledger `issue:c10c1e94f4b3` (major bug, discovered from FEAT-681): `_action_click`'s
text-contains branch calls `driver.execute_script(script, selector, js_text_filter)` with a
script that reads `arguments[0]` / `arguments[1]`. That is Selenium-only: Playwright/Page
drivers forward to `page.evaluate(script, *args)`, which accepts a single optional `arg` and
never binds `arguments`, so the click fails. Implements spec §3 Module 1.

---

## Scope

- Replace the `execute_script(script, selector, js_text_filter)` call with one
  `driver.evaluate(expr)` call, where `expr` is a self-contained IIFE embedding the CSS
  prefix and the lower-cased needle via `json.dumps`.
- Keep hit/miss behaviour: hit → `return True`; miss → the same `RuntimeError`.
- Add unit tests for the five cases in spec §4.

**NOT in scope**: the non-text click paths, the `selector_type == "text"` XPath quoting,
other `execute_script` call sites (`_action_scroll` has its own ledger issue), any FEAT-681 action.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | MODIFY | text-contains click via `driver.evaluate` |
| `packages/ai-parrot-tools/tests/scraping/test_executor.py` | MODIFY | add `TestClickTextContains` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import json  # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py:15
from parrot.tools.scraping.executor import _dispatch_step  # verified: tests/scraping/test_executor.py:8-14
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py
async def execute_script(self, script: str, *args: Any) -> Any:  # line 208
async def evaluate(self, expression: str) -> Any:  # line 220 (abstract; expression only)
# playwright_driver.py:269 / page_driver.py:177 → await self._page.evaluate(expression)
# selenium_driver.py:368 → execute_script(f"return {expression}")

# packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py
async def _action_click(driver: AbstractDriver, action: Any, default_timeout: int) -> bool:  # line 449
#   local names in scope at the edit site: selector (CSS prefix), js_text_filter (needle, str)
```

### Does NOT Exist
- ~~`AbstractDriver.evaluate(expression, *args)`~~ — `evaluate` takes the expression only.
- ~~`driver.click_text(...)`~~ — no such driver method.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/scraping/test_executor.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_action_click"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `json.dumps` output is a valid JS string literal — splice it into the expression; never
  pass values as script arguments (same rule as FEAT-681 `_action_submit`).
- Lower-case the needle in Python; the JS compares to `textContent.toLowerCase()`.
- Keep the diff confined to the text-contains block — FEAT-681 edits the same file.

---

## Implementation Blueprint

### Steps (in order)
1. Replace the `script = (...)` + `execute_script` block in `_action_click` with the block
   below — *why*: `evaluate(expression)` is the only JS entry point all three drivers implement identically.
2. Update the docstring to say the text filter runs as one `driver.evaluate` IIFE — *why*: spec §3 skeleton.
3. Add `TestClickTextContains` at the end of `test_executor.py` — *why*: spec §4.

### `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'hit = await driver.execute_script(script, selector, js_text_filter)' executor.py)
# REPLACE the `script = ( ... )` assignment and the execute_script line (executor.py:489-503) with:
        expr = (
            "(() => {"
            f" const els = document.querySelectorAll({json.dumps(selector)});"
            f" const needle = {json.dumps(js_text_filter.lower())};"
            " for (const el of els) {"
            "   if ((el.textContent || '').toLowerCase().includes(needle)) {"
            "     el.scrollIntoView({block:'center'});"
            "     el.dispatchEvent(new MouseEvent('click', "
            "       {bubbles: true, cancelable: true, view: window}));"
            "     return true;"
            "   }"
            " }"
            " return false;"
            "})()"
        )
        hit = await driver.evaluate(expr)
```
**Why**: Selenium's `evaluate` prefixes `return `, Playwright evaluates the expression; an
IIFE returns its boolean in both. The `RuntimeError` lines after it stay unchanged.

### `packages/ai-parrot-tools/tests/scraping/test_executor.py` (MODIFY)
```python
# APPEND at end of file
class TestClickTextContains:
    """FEAT-682: text-contains click runs as one driver.evaluate IIFE."""
    # FILL IN: the five tests of spec §4 using mock_driver + _dispatch_step / _action_click
```

### FILL IN checklist
- [ ] tests: uses evaluate (not execute_script / click), no `arguments[`, quote escaping, miss raises, plain selector unchanged

---

## Acceptance Criteria

- [ ] Text-contains click calls `driver.evaluate` once, never `driver.execute_script`.
- [ ] Selector and needle embedded with `json.dumps`; no `arguments[` in the expression.
- [ ] Miss → `RuntimeError`; hit → `True`; plain paths unchanged.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/scraping/test_executor.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_executor_driver_parity.py -q`

---

## Test Specification

```python
async def test_click_text_contains_uses_evaluate(mock_driver):
    mock_driver.evaluate = AsyncMock(return_value=True)
    action = MagicMock(selector="button:-soup-contains('Next')", selector_type="css", timeout=None)
    assert await _action_click(mock_driver, action, 10) is True
    expr = mock_driver.evaluate.await_args.args[0]
    assert json.dumps("button") in expr and json.dumps("next") in expr
    assert "arguments[" not in expr
    mock_driver.execute_script.assert_not_awaited()
    mock_driver.click.assert_not_awaited()
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug scraping-executor-fixes --feature-id FEAT-682`).
2. Verify the Codebase Contract, implement from the blueprint, run the Validation Commands.
3. Commit only the two listed files; close with `scripts/sdd/close_task.sh TASK-4358 scraping-executor-fixes verified`.

---

## Completion Note

**Completed by**: agent:sdd-fix (Claude Opus 5.5)
**Date**: 2026-10-15
**Notes**: `_action_click` text-contains branch now builds a self-contained IIFE with the CSS
prefix and lower-cased needle embedded via `json.dumps` and runs it with `driver.evaluate`
(no `arguments[N]`, no extra positional args). Hit/miss behaviour and the RuntimeError are
unchanged. Added `TestClickTextContains` (6 tests: evaluate-only, no `arguments[`, quote
escaping, miss raises, miss recorded as step error via `execute_plan_steps`, plain selector
unchanged). Validation: `test_executor.py` + `test_executor_driver_parity.py` → 47 passed.
Code commit: 4a43d239a.

Pre-existing, untouched: ruff F401 on the `EXTRACTOR_REGISTRY` import (executor.py:24).

**Deviations from spec**: one extra test (`..._miss_recorded_as_step_error`) beyond spec §4.
