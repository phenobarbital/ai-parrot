# TASK-4367: Obscura-safe load waits and page reads in `PlaywrightDriver`

**Feature**: FEAT-686 — fixgroup-eb3ff2211ad0
**Spec**: `sdd/specs/fixgroup-eb3ff2211ad0.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

Resolves ledger issue:b09cc5d3389d.

---

## Context
Spec §1: on Obscura 0.2.2, after a click-triggered navigation, `load`/`domcontentloaded`
never fire and Playwright's utility world (`content()`, locators) is broken, while
main-world `page.evaluate` keeps working.

---

## Scope
- `playwright_driver.py`: `_is_obscura` property; `_poll_ready_state(state, timeout)`;
  obscura branches in `wait_for_load_state` (load/domcontentloaded) and
  `wait_for_navigation`; evaluate fallbacks in `get_page_source` and `get_text`
  for non-timeout errors.
- Unit tests for every obscura branch plus the unchanged playwright path.

**NOT in scope**: locator actions on a renderer-navigated Obscura document;
`DriverRegistry` "obscura" entry; integration-test edits.

---

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py` | MODIFY | obscura-safe waits + read fallbacks |
| `packages/ai-parrot-tools/tests/scraping/test_playwright_driver.py` | MODIFY | unit tests for the obscura branches |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .abstract import AbstractDriver            # playwright_driver.py:11
from .playwright_config import PlaywrightConfig  # playwright_driver.py:12
```

### Existing Signatures to Use
```python
# playwright_driver.py
async def get_page_source(self) -> str: ...                                      # :222
async def get_text(self, selector: str, timeout: int = 10) -> str: ...           # :226
async def wait_for_navigation(self, timeout: int = 30) -> None: ...              # :278
async def wait_for_load_state(self, state: str = "load", timeout: int = 30) -> None: ...  # :282
def _resolve_selector(self, selector: str) -> str: ...                           # :479
# playwright_config.py:101
engine: str = "playwright"
```

### Does NOT Exist
- ~~`PlaywrightDriver._is_obscura`~~ / ~~`_poll_ready_state`~~ before this task.
- ~~top-level `import playwright`~~ in the driver module — keep it lazy.

---

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/scraping/test_playwright_driver.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py#PlaywrightDriver"
  ]
}
```

---

## Acceptance Criteria
- [ ] Obscura `wait_for_load_state("load"|"domcontentloaded")` / `wait_for_navigation` poll `document.readyState`; `networkidle` still delegates.
- [ ] Obscura `get_page_source` / `get_text` fall back to main-world `evaluate` on non-timeout errors; timeouts re-raise.
- [ ] Playwright-engine path unchanged; existing tests green.
- [ ] Real Obscura 0.2.2: the 3 `TestObscura*` integration tests pass; `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot-tools/tests/scraping/test_playwright_driver.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py -q -k Obscura`

## Completion Note
Completed 2026-10-15 (sdd-fix lane, ledger issue:b09cc5d3389d). Implementing commit 002ee190e.

- Root cause (reproduced against real Obscura 0.2.2): after a renderer-initiated
  navigation (form submit via `click()`), Obscura never emits `load` /
  `domcontentloaded`, and Playwright's utility world is broken for the new
  document (`content()`, locators and `screenshot()` fail with
  `utilityScript.evaluate is not a function` / `injected.eval is not a function`)
  until the next `goto()`. Main-world `page.evaluate` keeps working.
- Obscura mode only: `wait_for_load_state("load"|"domcontentloaded")` and
  `wait_for_navigation` poll `document.readyState` (100 ms, transient evaluate
  errors tolerated, builtin `TimeoutError` on deadline); `networkidle`/`commit`
  still delegate. `get_page_source`/`get_text` fall back to a main-world evaluate
  read on non-timeout errors (timeouts re-raise; no match → `LookupError`).
- **Scope extension**: `screenshot()` also needed a fallback (raw CDP
  `Page.captureScreenshot` via `new_cdp_session`) — the real test failed there
  once the earlier calls passed. Not listed in the original scope; same pattern.
- Playwright-engine path unchanged (asserted by a dedicated unit test).
- Tests: 10 new unit tests (72 in `test_playwright_driver.py` pass); the three
  real-Obscura `TestObscura*` integration tests pass (twice); whole
  `packages/ai-parrot-tools/tests/scraping` = 955 passed with obscura 0.2.2 on PATH;
  ruff + black clean.
- Still broken upstream (out of scope): locator actions (`fill`/`click`/
  `wait_for_selector`) on a renderer-navigated Obscura document.

### Merge note (2026-10-16)
This task was implemented twice in parallel: commit `002ee190e` (the shipped
implementation, described above) and an independent second pass in a worktree
branched from a much newer `origin/dev`. The two branches were reconciled with
a plain merge; `002ee190e`'s driver and tests were kept wholesale, because the
second pass had two real defects theirs does not:

- it passed a `_resolve_selector`-produced `xpath=<expr>` straight to
  `document.querySelector` in the `get_text` fallback (throws for XPath
  selectors; spec §2 requires the `document.evaluate` branch), and
- it omitted the doctype from the `get_page_source` fallback (spec §2 requires
  "doctype + outerHTML").

One improvement was carried over from the second pass: `_cdp_screenshot()` now
guards `session.detach()` so a detach failure cannot mask an otherwise
successful capture, with a unit test for it.

Also recorded from the second pass's full-suite run: three scraping tests
(`test_browsing_sequence_hover_type_submit_screenshot`,
`TestAuthenticatedFlowEndToEnd::test_login_survives_across_flow_nodes`,
`TestStubRegressionFullPlan::test_two_actions_produce_real_effects`) fail on
real Chromium with an empty `#query` value after typing. They were verified
failing identically on the pre-task baseline, so they are **pre-existing** and
unrelated to this task.

