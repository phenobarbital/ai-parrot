# TASK-4363: Read the scroll-to-bottom page height through `driver.evaluate`

**Feature**: FEAT-682 — Scraping Executor Fixes
**Spec**: `sdd/specs/scraping-executor-fixes.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4358
**Assigned-to**: unassigned
**discovered_from**: issue:9cbd2cf9f9f9

---

## Context

Ledger `issue:9cbd2cf9f9f9` (minor bug, discovered while fixing `issue:c10c1e94f4b3` in
TASK-4358): `_action_scroll(direction='bottom')` reads the page height with
`driver.execute_script("return Math.max(document.body.scrollHeight, ...)")`. Selenium wraps
scripts in a function body, so the top-level `return` is legal there; `PlaywrightDriver` and
`PageDriver` forward to `page.evaluate(script)`, where a top-level `return` is an
`Illegal return statement` SyntaxError — so scroll-to-bottom (the lazy-load trigger) fails on
those drivers. Same root cause as spec §3 Module 1, applied to the scroll path.

---

## Scope

- Replace `height_script` + its two `driver.execute_script(height_script)` calls in
  `_action_scroll` with `driver.evaluate(height_expr)`, where `height_expr` is the bare
  expression `Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)`
  (no `return`, no trailing `;`).
- Keep the chunked scroll loop, sleeps and `window.scrollTo` calls unchanged — those are
  statements without `return` and already work on every driver.
- Add unit tests for the bottom branch.

**NOT in scope**: the `top`/`down`/`up` branches, `_action_click` (TASK-4358), any other
`execute_script` call site.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | MODIFY | scroll-bottom height via `driver.evaluate` |
| `packages/ai-parrot-tools/tests/scraping/test_executor.py` | MODIFY | add `TestScrollBottom` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio  # verified: executor.py (used by _action_scroll's asyncio.sleep)
from parrot.tools.scraping.executor import _dispatch_step  # verified: tests/scraping/test_executor.py:9
from parrot.tools.scraping.models import ScrapingStep  # verified: tests/scraping/test_executor.py:17
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py
async def execute_script(self, script: str, *args: Any) -> Any:  # line 208
async def evaluate(self, expression: str) -> Any:  # line 220 (abstract; expression only)
# playwright_driver.py / page_driver.py → await self._page.evaluate(expression)
# selenium_driver.py → execute_script(f"return {expression}")

# packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py (feature branch, after TASK-4358)
async def _action_scroll(driver: AbstractDriver, action: Any) -> bool:  # ~line 540
#   height_script = "return Math.max(...)"  # ~line 555
#   height = int(await driver.execute_script(height_script) or 0)  # ~line 556
#   new_height = int(await driver.execute_script(height_script) or 0)  # ~line 564

# tests/scraping/test_executor.py
# fixture mock_driver (line 28): AsyncMock driver; TestDispatchStep.test_scroll_top (line 256)
```

### Does NOT Exist
- ~~`AbstractDriver.get_page_height()`~~ / ~~`driver.scroll_to_bottom()`~~ — no such driver methods.
- ~~`AbstractDriver.evaluate(expression, *args)`~~ — `evaluate` takes the expression only.

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
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_action_scroll"
  ]
}
```

---

## Implementation Notes

- The expression must not start with `return` and must not end in `;` — Selenium's
  `evaluate` prepends `return `, Playwright evaluates the bare expression.
- Patch `asyncio.sleep` in tests so the 6-chunk loop does not sleep 2.4 s.

---

## Implementation Blueprint

### Steps (in order)
1. Rename `height_script` → `height_expr`, drop `return` and `;`, and switch both reads to
   `driver.evaluate` — *why*: `evaluate(expression)` is the only JS-value entry point all
   three drivers implement identically.
2. Append `TestScrollBottom` to `test_executor.py` — *why*: regression guard for the issue.

### `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'height_script = "return Math.max' executor.py)
# REPLACE inside `if direction == "bottom":`
        height_expr = "Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
        height = int(await driver.evaluate(height_expr) or 0)
        # ... loop unchanged, except:
            new_height = int(await driver.evaluate(height_expr) or 0)
```
**Why**: removes the top-level `return` that is a SyntaxError under `page.evaluate`.

### `packages/ai-parrot-tools/tests/scraping/test_executor.py` (MODIFY)
```python
# APPEND at end of file
class TestScrollBottom:
    """FEAT-682 / issue:9cbd2cf9f9f9: scroll-bottom height read via driver.evaluate."""
    # FILL IN: tests per Test Specification below
```

### FILL IN checklist
- [ ] evaluate used for height (no `return` in the expression); scrollTo chunks still via execute_script
- [ ] zero height short-circuits after one evaluate call

---

## Acceptance Criteria

- [ ] `_action_scroll(direction='bottom')` reads height only via `driver.evaluate`; the
      expression contains no `return`.
- [ ] No `execute_script` call in the bottom branch receives a script starting with `return`.
- [ ] `top`/`down`/`up` behaviour unchanged (existing tests pass).
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/scraping/test_executor.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_executor_driver_parity.py -q`

---

## Test Specification

```python
async def test_scroll_bottom_uses_evaluate(mock_driver):
    mock_driver.evaluate = AsyncMock(return_value=1200)
    step = ScrapingStep.from_dict({"action": "scroll", "direction": "bottom"})
    with patch("asyncio.sleep", new=AsyncMock()):
        await _dispatch_step(mock_driver, step, ...)
    expr = mock_driver.evaluate.await_args_list[0].args[0]
    assert "return" not in expr and "scrollHeight" in expr
    for call in mock_driver.execute_script.await_args_list:
        assert not call.args[0].lstrip().startswith("return")
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug scraping-executor-fixes --feature-id FEAT-682`).
2. Verify the Codebase Contract, implement from the blueprint, run the Validation Commands.
3. Commit only the two listed files; close with `scripts/sdd/close_task.sh TASK-4363 scraping-executor-fixes verified`.

---

## Completion Note

Implemented in 4001ff70d (via /sdd-fix, issue:9cbd2cf9f9f9). `_action_scroll` bottom branch now
reads the height with `driver.evaluate("Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)")`
(both reads); chunked `window.scrollTo` calls unchanged. Added `TestScrollBottom` (2 tests) — both fail
against the old code. Validation: `test_executor.py` + `test_executor_driver_parity.py` → 49 passed; ruff clean.
Note: FEAT-682's PR #1675 was already open when this task was added; this commit lands on the same branch.
