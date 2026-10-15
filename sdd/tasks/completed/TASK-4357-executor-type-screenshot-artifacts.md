# TASK-4357: Execute typing and report screenshot artifacts

**Feature**: FEAT-681 - Browsing Executor Action Gaps
**Spec**: `sdd/specs/browsing-executor-action-gaps.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4355, TASK-4356
**Assigned-to**: unassigned

## Context

Implement the assigned portion of approved FEAT-681 §§2–7. Browsing replays saved actions through the standalone executor; model validation currently accepts actions that execution does not fully support.

## Scope

Complete M2 typing/screenshot behavior and remaining M3 unit/integration coverage. Keep existing hover/submit handlers and their tests. Use a separate screenshot test module plus the local fixture to bound file ownership.

**NOT in scope**: legacy `scraping/tool.py`, `_action_click` repairs (ledger issue:c10c1e94f4b3), new dependencies, model changes, Selenium full-page emulation, or public executor signature changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` | MODIFY | Type dispatch and screenshot payloads |
| `packages/ai-parrot-tools/tests/scraping/test_executor_screenshot_gaps.py` | CREATE | Type/screenshot unit tests |
| `packages/ai-parrot-tools/tests/scraping/test_browsing_action_sequence.py` | CREATE | Real-browser sequence test |
| `packages/ai-parrot-tools/tests/scraping/fixtures/action_gaps.html` | CREATE | Local browser fixture |
| `packages/ai-parrot-tools/tests/test_path_confinement_pa14.py` | MODIFY | Fake driver `screenshot` accepts `full_page` (regression from screenshot signature) |

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
import base64
import inspect
from parrot_tools.scraping.confine import FILES_ROOT, confined_file
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver
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
- `executor.py:317,869`: screenshot currently calls `_action_screenshot(driver, action)` and discards driver bytes; preserve path assembly while replacing this private handler.
- `confine.py:18,45`: FILES_ROOT is a ContextVar; `confined_file(directory: str | Path, filename: str) -> Optional[Path]` validates the final joined path or returns None when unconfined.
- `models.py:92,587,606`: Type has text, selector=None, delay=0, clear_first=False; Screenshot has full_page=True, selector=None, return_base64=False, output_path/output_name and get_filename().
- `drivers/playwright_driver.py:29`: PlaywrightDriver(config=None) exposes async start(), navigate(url, timeout=30), quit().
- TASK-4355 creates type_text(self, text: str, selector: Optional[str] = None, delay_ms: int = 0, clear_first: bool = False, timeout: int = 10) -> None and screenshot_element(self, selector: str, path: str, timeout: int = 10) -> bytes.
- TASK-4356 creates hover/submit dispatch; reverify executor anchors after it lands.

Exact existing symbol references:
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#execute_plan_steps`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_dispatch_step`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_action_screenshot`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/models.py#Type`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/models.py#Screenshot`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/models.py#ScrapingStep`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/confine.py#confined_file`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py#AbstractDriver`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py#PlaywrightDriver`
- `sym:packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py#ScrapingPlan`

### Does NOT Exist

- `_action_type` and MAX_SCREENSHOT_BASE64_BYTES do not exist before this task.
- Driver type_text/screenshot_element exist only after TASK-4355.
- No screenshot payload model is needed; extracted_data holds dictionaries.

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
      "path": "packages/ai-parrot-tools/tests/scraping/test_executor_screenshot_gaps.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/scraping/test_browsing_action_sequence.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/scraping/fixtures/action_gaps.html",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#execute_plan_steps",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_dispatch_step",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py#_action_screenshot",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/models.py#Type",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/models.py#Screenshot",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/models.py#ScrapingStep",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/confine.py#confined_file",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py#AbstractDriver",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py#PlaywrightDriver",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py#ScrapingPlan"
  ]
}
```

## Implementation Notes

Consumes AbstractDriver.type_text and screenshot_element from TASK-4355; depends on TASK-4356 for overlapping executor.py writes and the hover/submit handlers exercised by integration.
Use async I/O, existing logging, Google docstrings and strict type hints. Format touched Python with black (120 columns) and run ruff check. Store validation logs in artifacts/logs/. Do not leave blueprint placeholders in implementation files.

## Implementation Blueprint

### Steps (in order)

1. Reverify predecessor changes — executor.py has changed since planning.
2. Wire typing and rewrite screenshot — use the driver capabilities and shared extracted-data accumulator.
3. Test cap, collision and confinement boundaries — output metadata must neither overwrite earlier captures nor escape its root.
4. Run a real local browser sequence — verify form JavaScript, actual typing and both capture modes.

### `packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py` (MODIFY)
```python
# Anchor:     elif action_type == "screenshot":
# occurrences: 1 (verified with grep -F -c; packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py:317)
# Update screenshot branch to pass step and the shared accumulator:
    elif action_type == "screenshot":
        return await _action_screenshot(driver, action, step, step_extracted)
# Insert a type branch beside other action branches:
    elif action_type == "type":
        return await _action_type(driver, action, timeout)
# Add stdlib import base64, preserving existing imports.
MAX_SCREENSHOT_BASE64_BYTES: int = 2 * 1024 * 1024
"""Maximum raw PNG bytes included as base64 in extracted_data."""

async def _action_type(driver: AbstractDriver, action: Any, default_timeout: int) -> bool:
    """Forward typing fields to the optional driver capability."""
    await driver.type_text(action.text, selector=action.selector, delay_ms=action.delay,
                           clear_first=action.clear_first, timeout=action.timeout or default_timeout)
    return True

# REPLACE complete old _action_screenshot, verified at executor.py:869 (occurrences: 1).
async def _action_screenshot(
    driver: AbstractDriver, action: Any, step: ScrapingStep, step_extracted: Dict[str, Any],
) -> bool:
    """Capture a page or element and report its path and bounded optional base64."""
    # FILL IN: preserve existing confined_file/output_path/get_filename logic; AC-2.
    # Selected: screenshot_element(selector, full_path, action.timeout or _DEFAULT_TIMEOUT).
    # Otherwise screenshot(full_path, full_page=action.full_page).
    # FILL IN: record path and capped base64 from returned bytes; AC-3.
    # Use action.name unless default/empty, then screenshot; choose first free _2/_3 suffix.
    # Keep step argument for handler consistency; do not change public dispatch signature.
    return True
```
**Why**: The step accumulator survives plan completion; returning only True loses the screenshot artifact. The fixed private signature uses the executor default when no action timeout is set.

### `packages/ai-parrot-tools/tests/scraping/test_executor_screenshot_gaps.py` (CREATE)
```python
"""Type and screenshot output regression tests."""
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
import base64
import inspect
from parrot_tools.scraping.confine import FILES_ROOT

@pytest.fixture
def spy_driver() -> AsyncMock:
    """Return fake PNG bytes and final DOM content."""
    driver = AsyncMock()
    driver.current_url = "http://x/"
    driver.get_page_source.return_value = "<html></html>"
    driver.screenshot.return_value = b"\x89PNG"
    driver.screenshot_element.return_value = b"\x89PNG"
    return driver

async def test_screenshot_return_base64(spy_driver: AsyncMock, tmp_path: Path) -> None:
    """Result base64 decodes to precisely the captured bytes."""
    # FILL IN: run screenshot plan with temp output path and assert payload; AC-3.

async def test_every_action_map_entry_is_dispatched() -> None:
    """All registered opcodes have dispatch branches."""
    # FILL IN: compare ACTION_MAP keys with inspect.getsource(_dispatch_step); AC-4.
# FILL IN: remaining type/screenshot cases in Test Specification, including confinement.
```
**Why**: Separate test module avoids rewriting TASK-4356 tests while extending executor coverage.

### `packages/ai-parrot-tools/tests/scraping/test_browsing_action_sequence.py` (CREATE)
```python
"""Local-browser integration for hover, typing, submit and screenshots."""
from pathlib import Path
import pytest
from parrot_tools.scraping.drivers.playwright_driver import PlaywrightDriver
from parrot_tools.scraping.executor import execute_plan_steps

async def test_browsing_sequence_hover_type_submit_screenshot(tmp_path: Path) -> None:
    """Run the local fixture through the real executor and browser driver."""
    # FILL IN: start driver, navigate to sibling fixtures/action_gaps.html file URI.
    # Skip only absent Playwright/package/browser executable, never arbitrary test failures.
    # Run hover/type/submit and element plus full-page screenshots; AC-5.
    # Assert DOM evidence and reported on-disk PNGs. Always await driver.quit() in finally.
```
**Why**: A real local page verifies JavaScript and keystroke behavior that mocks cannot.

### `packages/ai-parrot-tools/tests/scraping/fixtures/action_gaps.html` (CREATE)
```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Action gaps fixture</title></head>
<body>
<!-- FILL IN: hover-controlled menu, #query input and form, visible submit result.
     Use deterministic inline CSS/JS with no external assets; bound by AC-5.
     Give body enough height to distinguish viewport and full-page screenshots.
     Handle submit locally with preventDefault, recording entered value and event. -->
</body>
</html>
```
**Why**: A static local fixture keeps integration independent of external sites or shared services.

### FILL IN checklist

- [ ] Complete packages/ai-parrot-tools/src/parrot_tools/scraping/executor.py according to its bounded blueprint and AC below.
- [ ] Complete packages/ai-parrot-tools/tests/scraping/test_executor_screenshot_gaps.py according to its bounded blueprint and AC below.
- [ ] Complete packages/ai-parrot-tools/tests/scraping/test_browsing_action_sequence.py according to its bounded blueprint and AC below.
- [ ] Complete packages/ai-parrot-tools/tests/scraping/fixtures/action_gaps.html according to its bounded blueprint and AC below.

## Acceptance Criteria

- [ ] AC-1: Type forwards all fields exactly, including selector=None and timeout fallback.
- [ ] AC-2: Screenshot forwards full_page; a selector uses screenshot_element only. Preserve confined_file behavior and default filenames without changing public signatures.
- [ ] AC-3: Always record path; return_base64 includes base64 at <=2 MiB, otherwise omits it and adds base64_omitted=True/size_bytes with a warning. No base64 fields when not requested. Custom names and repeated names use first free suffix without overwrites.
- [ ] AC-4: Every ACTION_MAP opcode has dispatch coverage and unknown opcodes still return False.
- [ ] AC-5: Local integration proves hover reveals menu, typing generates input, form submission records value, screenshots exist and are reported; skip only missing browser tooling.
- [ ] AC-6: Focused and existing regression tests pass; black and ruff are clean.

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/scraping/test_executor_screenshot_gaps.py packages/ai-parrot-tools/tests/scraping/test_stub_closure_regression.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_browsing_action_sequence.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_executor.py packages/ai-parrot-tools/tests/scraping/test_executor_driver_parity.py -q`

## Test Specification

Implement every remaining M2 test from spec §4: type_forwards_all_fields, type_without_selector, screenshot_passes_full_page, screenshot_element_uses_screenshot_element, screenshot_records_path, screenshot_return_base64, screenshot_base64_cap (exact cap and cap+1), screenshot_key_collision_suffix, screenshot_custom_name_key, every_action_map_entry_is_dispatched. Prefix each name with test_. Add preoccupied suffix/custom-name collision tests, failed-capture absence of payload, and path-traversal rejection with FILES_ROOT token reset in finally. Integration must validate actual DOM effects, file bytes and full-page dimensions versus viewport.

## Agent Instructions

1. Use `$sdd-start TASK-4357` to provision the feature worktree; do not implement on dev.
2. Read the spec and verify dependencies are done in `sdd/tasks/index/browsing-executor-action-gaps.json`.
3. Reverify anchors and imports after dependencies land, then complete the blueprint within declared files.
4. Run Validation Commands, black and ruff; record evidence and commit only scoped files.
5. Finalize with `scripts.sdd.finalize_task` and real `TaskCompletionEvidence` for the implementation HEAD (Codex adaptation); do not manually move tasks or use legacy close_task.sh.

## Completion Note


- Task: TASK-4357
- Feature: browsing-executor-action-gaps
- Implementation SHA: 9de6e834691bea51ec368b13744745fc9a32cc2a
- Closed at (UTC): 2026-10-15T17:34:03+00:00
- Fix commits: 54162a3c0bebd23a79a933a07777dd88c710e2c2, 78d13543ba66da83ba4a9a299df565b3c7cf3f8b, 9de6e834691bea51ec368b13744745fc9a32cc2a

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 3 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 415.8s · Tokens: n/a |
| validation_note | Merge-tier exit 1: 15 failures identical to origin/dev baseline (chromedriver RO fs, obscura/playwright env, legacy MagicMock-await toolkit tests); no new failures after review fixes. |
