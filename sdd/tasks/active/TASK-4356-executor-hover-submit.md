# TASK-4356: Execute hover and submit actions

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

Implement the hover and submit subset of M2, its M3 unit tests, and repair the unknown-action regression. Do not implement type/screenshot in this task.

**NOT in scope**: legacy `scraping/tool.py`, `_action_click` repairs (ledger issue:c10c1e94f4b3), new dependencies, model changes, Selenium full-page emulation, or public executor signature changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | MODIFY | Hover/submit dispatch and handlers |
| `packages/ai-parrot-tools/tests/scraping/test_stub_closure_regression.py` | MODIFY | Use truly unknown opcode |
| `packages/ai-parrot-tools/tests/scraping/test_executor_action_gaps.py` | CREATE | Hover/submit unit coverage |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import pytest
import json
from parrot_tools.scraping import executor as executor_module
from parrot_tools.scraping.executor import execute_plan_steps
from parrot_tools.scraping.drivers.abstract import AbstractDriver
from parrot_tools.scraping.models import ScrapingStep, ACTION_MAP
from parrot_tools.scraping.plan import ScrapingPlan
```

Imports verified against the named source modules; stdlib imports are built-in. pytest is already used in the neighboring regression tests. Playwright and Selenium are existing scraping extras in packages/ai-parrot-tools/pyproject.toml:73. Relative imports in modified modules retain their existing spelling.

### Existing Signatures to Use

- `executor.py:60`: `execute_plan_steps(driver, plan=None, steps=None, selectors=None, config=None, base_url=None, credential_resolver=None, channel=None) -> ScrapingResult`.
- `executor.py:264`: `_dispatch_step(driver, step, base_url, timeout, step_extracted, *, credential_resolver=None, channel=None) -> bool`.
- `executor.py:142-176`: handler exceptions become `metadata["step_errors"]`; only navigate/authenticate abort.
- `executor.py:194`: `extracted_data = dict(step_extracted)` preserves step outputs.
- `models.py:22,26`: action timeout is optional; `get_action_type()` reads action opcode, not free-form name.
- `models.py`: `ScrapingStep.from_dict` parses registered actions; unknown opcodes cannot be tested through raw dict validation.
- `plan.py:63`: `ScrapingPlan(BaseModel)` accepts `url`, `objective`, and `steps`.
- `executor.py:449`: `_action_click(driver, action, default_timeout) -> bool` maps text to XPath; reuse mapping semantics only.
- `executor.py:954`: `_strip_soup_only_pseudos(selector: str) -> str` strips BS4-only pseudos.
- `drivers/abstract.py:70,109,177,220`: async click/hover take `(selector: str, timeout: int = 10)`; wait_for_selector adds `state: str = "visible"`; evaluate takes only `expression: str`.
- `models.py:79,245`: Hover has selector_type; Submit has selector, wait_after_submit and wait_timeout=5, but no selector_type.
- `test_stub_closure_regression.py:85`: `TestStubClosure.test_unknown_action_returns_false(self, spy_driver)` currently uses hover.

Exact existing symbol references:
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#execute_plan_steps`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_dispatch_step`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_action_click`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_strip_soup_only_pseudos`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py#AbstractDriver`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/models.py#Hover`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/models.py#Submit`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/models.py#ScrapingStep`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py#ScrapingPlan`

### Does NOT Exist

- `_resolve_locator`, `_action_hover` and `_action_submit` do not exist yet.
- `Submit.selector_type` and driver.submit do not exist.
- No portable execute_script positional-argument contract exists for Playwright.

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
      "path": "packages/ai-parrot-tools/tests/scraping/test_stub_closure_regression.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/scraping/test_executor_action_gaps.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#execute_plan_steps",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_dispatch_step",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_action_click",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_strip_soup_only_pseudos",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py#AbstractDriver",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/models.py#Hover",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/models.py#Submit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/models.py#ScrapingStep",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py#ScrapingPlan"
  ]
}
```

## Implementation Notes

Independent of TASK-4355: hover, evaluate, click and wait_for_selector already exist; owns executor.py and hover/submit tests in the first wave.
Use async I/O, existing logging, Google docstrings and strict type hints. Format touched Python with black (120 columns) and run ruff check. Store validation logs in artifacts/logs/. Do not leave blueprint placeholders in implementation files.

## Implementation Blueprint

### Steps (in order)

1. Add helper and handlers — only existing driver capabilities are required.
2. Wire hover and submit branches — retain unknown fallback for unsupported opcodes.
3. Rewrite unknown-opcode test — hover is now a supported operation.
4. Test end-to-end executor error handling and expression portability — prevent silent successes.

### `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` (MODIFY)
```python
# Anchor:     elif action_type == "screenshot":
# occurrences: 1 (verified with grep -F -c; packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py:317)
# In _dispatch_step, insert these branches immediately before the screenshot branch:
    elif action_type == "hover":
        return await _action_hover(driver, action, timeout)
    elif action_type == "submit":
        return await _action_submit(driver, action, timeout)
# Add the following module-level helpers before existing _action_screenshot:
def _resolve_locator(selector: str, selector_type: str = "css") -> str:
    """Map CSS, XPath or text DSL selectors to a driver locator."""
    # FILL IN: css strips soup pseudos; xpath unchanged; text mirrors click mapping; AC-1.

async def _action_hover(driver: AbstractDriver, action: Any, default_timeout: int) -> bool:
    """Hover over the resolved selector using the action or default timeout."""
    timeout = action.timeout or default_timeout
    await driver.hover(_resolve_locator(action.selector, action.selector_type), timeout)
    return True

async def _action_submit(driver: AbstractDriver, action: Any, default_timeout: int) -> bool:
    """Submit a form or click a control; raise RuntimeError for a missing element."""
    timeout = action.timeout or default_timeout
    # FILL IN: one evaluate IIFE embeds json.dumps(action.selector); AC-2.
    # Resolve / or ./ via document.evaluate; otherwise querySelector.
    # Return missing/form/click; form uses requestSubmit() with submit() fallback.
    # Missing raises RuntimeError; click awaits driver.click(action.selector, timeout).
    # Await wait_for_selector(action.wait_after_submit, action.wait_timeout) when set.
    return True
```
**Why**: Use one expression with JSON-embedded data because multi-argument execute_script is not portable. Leave _action_click unchanged.

### `packages/ai-parrot-tools/tests/scraping/test_stub_closure_regression.py` (MODIFY)
```python
# Anchor:     async def test_unknown_action_returns_false(self, spy_driver):
# occurrences: 1 (verified with grep -F -c; packages/ai-parrot-tools/tests/scraping/test_stub_closure_regression.py:85)
# Replace ONLY this test body; preserve its signature and neighboring tests.
        # FILL IN: build a MagicMock step whose action.get_action_type returns
        # "__unsupported_action__"; assert opcode absent from ACTION_MAP.
        # Call executor_module._dispatch_step(spy_driver, step, "http://x/", 10, {}).
        # Assert result is False. Add MagicMock and ACTION_MAP imports.
```
**Why**: A genuinely unknown opcode tests fallback after hover becomes supported; bypass raw-dict validation.

### `packages/ai-parrot-tools/tests/scraping/test_executor_action_gaps.py` (CREATE)
```python
"""Hover and submit behavior through the standalone executor."""
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import pytest
import json
from parrot_tools.scraping import executor as executor_module
from parrot_tools.scraping.executor import execute_plan_steps
from parrot_tools.scraping.drivers.abstract import AbstractDriver
from parrot_tools.scraping.models import ScrapingStep, ACTION_MAP
from parrot_tools.scraping.plan import ScrapingPlan

@pytest.fixture
def spy_driver() -> AsyncMock:
    """Build a driver that can complete result extraction."""
    driver = AsyncMock()
    driver.get_page_source.return_value = "<html></html>"
    driver.current_url = "http://x/"
    return driver

async def test_hover_css_calls_driver_hover(spy_driver: AsyncMock) -> None:
    """A hover step invokes its driver method."""
    # FILL IN: execute a one-step plan and assert exact await plus no errors; AC-1.

async def test_submit_missing_records_error(spy_driver: AsyncMock) -> None:
    """Missing submit targets record an error without aborting later steps."""
    # FILL IN: evaluate returns missing; assert metadata and next step execution; AC-3.
# FILL IN: all remaining hover/submit tests enumerated in Test Specification below.
```
**Why**: Exercise result/error handling as well as individual dispatch calls.

### FILL IN checklist

- [ ] Complete packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py according to its bounded blueprint and AC below.
- [ ] Complete packages/ai-parrot-tools/tests/scraping/test_stub_closure_regression.py according to its bounded blueprint and AC below.
- [ ] Complete packages/ai-parrot-tools/tests/scraping/test_executor_action_gaps.py according to its bounded blueprint and AC below.

## Acceptance Criteria

- [ ] AC-1: Hover strips soup pseudos for CSS, preserves XPath and maps text as specified; forwards action.timeout or default_timeout.
- [ ] AC-2: Submit evaluates one JSON-safe IIFE, resolves CSS/XPath, calls requestSubmit or submit fallback on forms, clicks non-form controls and optionally waits with wait_timeout.
- [ ] AC-3: Missing selector raises RuntimeError handled as a step error; subsequent noncritical steps continue.
- [ ] AC-4: Submit never calls execute_script; selector quotes and backslashes stay data.
- [ ] AC-5: Unknown opcode returns False; all hover/submit and stub regression tests pass.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/scraping/test_executor_action_gaps.py packages/ai-parrot-tools/tests/scraping/test_stub_closure_regression.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_executor.py -q`

## Test Specification

Implement spec tests test_hover_css_calls_driver_hover, test_hover_text_selector_builds_xpath, test_submit_form_uses_request_submit, test_submit_button_clicks, test_submit_missing_records_error, test_submit_waits_after and test_submit_selector_is_json_embedded. Add XPath, CSS pseudo stripping, timeout override, requestSubmit fallback expression checks and special-character selectors. Mock evaluate responses; real form execution is covered by TASK-4357.

## Agent Instructions

1. Use `$sdd-start TASK-4356` to provision the feature worktree; do not implement on dev.
2. Read the spec and verify dependencies are done in `sdd/tasks/index/browsing-executor-action-gaps.json`.
3. Reverify anchors and imports after dependencies land, then complete the blueprint within declared files.
4. Run Validation Commands, black and ruff; record evidence and commit only scoped files.
5. Finalize with `scripts.sdd.finalize_task` and real `TaskCompletionEvidence` for the implementation HEAD (Codex adaptation); do not manually move tasks or use legacy close_task.sh.

## Completion Note

Pending implementation; finalization owns this section.
