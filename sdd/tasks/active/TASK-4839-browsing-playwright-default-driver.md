# TASK-4839: Default driver → Playwright

**Feature**: FEAT-763 — browsing-playwright-default-and-screencast
**Spec**: `sdd/specs/browsing-playwright-default-and-screencast.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 1. `WebScrapingToolkit`/`WebBrowsingToolkit` and
the underlying `DriverFactory` currently default to the Selenium/Chrome
backend when a caller does not pass `driver_type`, even though this
repo's own `PlaywrightDriver` is the more capable, actively maintained
backend. This task flips three literal `"selenium"` defaults to
`"playwright"`. It is a pure default-value change — no new code paths, no
new behavior, additive only (`driver_type="selenium"`/`"obscura"` keep
working exactly as before).

This is the foundation task for the feature: TASK-4840 (screencast config
plumbing) and TASK-4841 (recording capture + MCP exposure) both build on
top of it.

---

## Scope

- Change `DriverConfig.driver_type`'s default from `"selenium"` to
  `"playwright"` (`toolkit_models.py:114`).
- Change `WebScrapingToolkit.__init__`'s `driver_type` parameter default
  from `"selenium"` to `"playwright"` (`toolkit.py:308`).
- Change `DriverFactory.create()`'s dict-fallback default from
  `"selenium"` to `"playwright"` (`driver_factory.py:94`).
- Fix the two existing tests whose assertions encode the OLD implicit
  default and would otherwise start failing (`test_toolkit_models.py`,
  `test_toolkit.py`).
- Fix/rewrite the three existing `test_driver_factory.py` tests that rely
  on the implicit default (one must be renamed and rewritten to assert
  the new Playwright behavior; two need an explicit `"driver_type":
  "selenium"` added to their config dict so they keep testing what they
  were actually written to test — browser/headless/auto_install
  forwarding — independent of which driver is the default).
- Add the net-new tests from spec §4 that pin down the new default and
  confirm explicit selections are unaffected.

**NOT in scope**:
- `record_video`/screencast plumbing — TASK-4840.
- `PlaywrightDriver.quit()`, `WebBrowsingToolkit.close_browser()`,
  `.parrot/mcp-toolkits.yaml` — TASK-4841.
- `parrot_tools.scraping.tool.WebScrapingTool` (module `tool.py`, not
  `toolkit.py`) — a separate, legacy class with its OWN independent
  `driver_type: Literal[...] = "selenium"` default at `tool.py:313`. It
  does not read `DriverConfig`'s or `DriverFactory.create()`'s default at
  all (it always passes `"driver_type": driver_type` explicitly into the
  dict it hands to `DriverFactory.create()`), so it is correctly
  unaffected by this task — do not touch `tool.py` or its tests
  (`test_tool_driver_integration.py`, `test_driver_integration.py`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py` | MODIFY | `DriverConfig.driver_type` default → `"playwright"` |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py` | MODIFY | `WebScrapingToolkit.__init__`'s `driver_type` default → `"playwright"` |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py` | MODIFY | `DriverFactory.create()`'s dict-fallback default → `"playwright"` |
| `packages/ai-parrot-tools/tests/scraping/test_toolkit_models.py` | MODIFY | fix `TestDriverConfig.test_defaults` assertion |
| `packages/ai-parrot-tools/tests/scraping/test_toolkit.py` | MODIFY | fix `TestConstructor.test_default_config` assertion |
| `packages/ai-parrot-tools/tests/scraping/test_driver_factory.py` | MODIFY | rename/rewrite `test_default_creates_selenium`; add explicit `driver_type` to `test_dict_config_selenium` / `test_dict_config_auto_install` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.toolkit_models import DriverConfig   # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py:71
from parrot_tools.scraping.toolkit import WebScrapingToolkit     # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:266
from parrot_tools.scraping.driver_factory import DriverFactory   # verified: packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py:31
```
The existing test files import through the legacy redirected path instead
(works via the `parrot.tools.<x>` → `parrot_tools.<x>` `sys.meta_path`
finder) — e.g. `test_toolkit_models.py` has
`from parrot.tools.scraping.toolkit_models import DriverConfig, ...` and
`test_driver_factory.py` has
`from parrot.tools.scraping.driver_factory import DriverFactory`
(verified: both files' own top-of-file imports). **Keep each existing
test file's current import style — do not change it to
`parrot_tools...` while fixing these tests.**

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py:114
driver_type: Literal["selenium", "playwright", "obscura"] = "selenium"   # change the default literal only

# packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py:308
driver_type: Literal["selenium", "playwright", "obscura"] = "selenium",  # change the default literal only

# packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py:94
driver_type: str = config.get("driver_type", "selenium")   # change the fallback literal only
```

### Existing Tests That Break (verified by direct read, 2026-10-27)
```python
# packages/ai-parrot-tools/tests/scraping/test_toolkit_models.py:16 (inside TestDriverConfig.test_defaults)
assert config.driver_type == "selenium"   # → "playwright"

# packages/ai-parrot-tools/tests/scraping/test_toolkit.py:121 (inside TestConstructor.test_default_config)
assert toolkit._config.driver_type == "selenium"   # → "playwright"
# `toolkit` fixture (test_toolkit.py:40-44) constructs WebScrapingToolkit(headless=True, plans_dir=..., llm_client=...)
# with NO driver_type arg — this is exactly the implicit-default path.

# packages/ai-parrot-tools/tests/scraping/test_driver_factory.py:34-38
@patch("parrot.tools.scraping.drivers.selenium_driver.SeleniumDriver")
def test_default_creates_selenium(self, mock_cls):
    mock_cls.return_value = MagicMock(spec=AbstractDriver)
    driver = DriverFactory.create()
    mock_cls.assert_called_once_with(browser="chrome", headless=True, auto_install=True, mobile=False)
    assert isinstance(driver, AbstractDriver)
# DriverFactory.create() with NO config now takes the "playwright" branch — rename+rewrite (see blueprint).

# packages/ai-parrot-tools/tests/scraping/test_driver_factory.py:152-156
@patch("parrot.tools.scraping.drivers.selenium_driver.SeleniumDriver")
def test_dict_config_selenium(self, mock_cls):
    mock_cls.return_value = MagicMock(spec=AbstractDriver)
    DriverFactory.create({"browser": "firefox", "headless": False})   # no driver_type key!
    mock_cls.assert_called_once_with(browser="firefox", headless=False, auto_install=True, mobile=False)

# packages/ai-parrot-tools/tests/scraping/test_driver_factory.py:158-162
@patch("parrot.tools.scraping.drivers.selenium_driver.SeleniumDriver")
def test_dict_config_auto_install(self, mock_cls):
    mock_cls.return_value = MagicMock(spec=AbstractDriver)
    DriverFactory.create({"auto_install": False})   # no driver_type key!
    mock_cls.assert_called_once_with(browser="chrome", headless=True, auto_install=False, mobile=False)
```

### Does NOT Exist
- ~~`parrot_tools.scraping.tool.WebScrapingTool`'s default changing~~ — that
  class has its own independent `driver_type` default (`tool.py:313`),
  untouched by this task (see Scope).
- ~~A shared `DriverFactory.DEFAULT_DRIVER_TYPE` constant~~ — does not
  exist; the default is a literal written in each of the three places
  above, not a shared constant.
- ~~`test_driver_integration.py` / `test_tool_driver_integration.py`
  needing changes~~ — they test `WebScrapingTool` (module `tool.py`), not
  `WebScrapingToolkit`/`DriverFactory`'s dict-fallback; unaffected,
  verified by direct read.

### Edit Sites (from spec §6, re-verified 2026-10-27 — HEAD `f7a5ff24d`)
| File | Anchor | Occurrences |
|---|---|---|
| `toolkit_models.py:114` | `driver_type: Literal["selenium", "playwright", "obscura"] = "selenium"` | 1 |
| `toolkit.py:308` | `driver_type: Literal["selenium", "playwright", "obscura"] = "selenium",` | 1 |
| `driver_factory.py:94` | `driver_type: str = config.get("driver_type", "selenium")` | 1 |

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/scraping/test_toolkit_models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/scraping/test_toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-tools/tests/scraping/test_driver_factory.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py#DriverConfig",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py#WebScrapingToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py#DriverFactory"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- This is a pure literal swap in the three source files — no structural
  changes, no new imports needed (the `Literal[...]` type annotation
  already includes `"playwright"` as a valid value in all three places).
- `self.logger` / docstrings: no changes needed — none of the three
  literals appear in a docstring or log message.
- Keep each test file's existing import style and test class structure;
  only touch the specific assertions/bodies called out above.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py:98-129` —
  the `"playwright"` branch `test_default_creates_playwright` (the
  renamed test) should mirror, since `DriverFactory.create()` with no
  config now takes this exact branch.
- `packages/ai-parrot-tools/tests/scraping/test_driver_factory.py:47-53` —
  `test_playwright_driver_type` is the existing pattern for mocking
  `PlaywrightConfig`/`PlaywrightDriver`; reuse it for the rewritten
  `test_default_creates_playwright`.

---

## Implementation Blueprint

### Steps (in order)
1. Flip the three default literals (`toolkit_models.py:114`,
   `toolkit.py:308`, `driver_factory.py:94`) — *why*: this is the whole
   behavioral change; doing all three together keeps `DriverConfig`,
   `WebScrapingToolkit`, and the raw-dict `DriverFactory.create()` path
   consistent with each other at every intermediate commit.
2. Fix `test_toolkit_models.py:16` and `test_toolkit.py:121` — *why*:
   these two assertions hard-code the old default and will fail the
   moment step 1 lands; fixing them in the same commit keeps the suite
   green.
3. Rename and rewrite `test_driver_factory.py`'s
   `test_default_creates_selenium` → `test_default_creates_playwright`,
   mirroring `test_playwright_driver_type`'s mocking pattern — *why*:
   `DriverFactory.create()` with no config now takes the `"playwright"`
   branch, so the old Selenium-mocking body no longer exercises what the
   test name claims.
4. Add `"driver_type": "selenium"` to the two dict-literal configs in
   `test_dict_config_selenium` and `test_dict_config_auto_install` —
   *why*: these two tests exist to verify `browser`/`headless`/
   `auto_install` dict-key forwarding, not which driver is the default;
   pinning `driver_type` explicitly keeps that intent correct regardless
   of the default.
5. Add the net-new tests from spec §4 (`test_driver_config_defaults_to_playwright`,
   `test_web_scraping_toolkit_defaults_to_playwright`,
   `test_driver_factory_dict_fallback_defaults_to_playwright`,
   `test_driver_factory_create_explicit_selenium_still_works`) — *why*:
   pins the new default and proves the change is additive (explicit
   `"selenium"` still works), matching spec Acceptance Criteria.

### `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'driver_type: Literal\["selenium", "playwright", "obscura"\] = "selenium"' packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit_models.py)
# REPLACE line 114:
    driver_type: Literal["selenium", "playwright", "obscura"] = "selenium"
# WITH:
    driver_type: Literal["selenium", "playwright", "obscura"] = "playwright"
```
**Why this shape**: single literal swap, no other change to the field or
its docstring above it.

### `packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'driver_type: Literal\["selenium", "playwright", "obscura"\] = "selenium",' packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py)
# REPLACE line 308:
        driver_type: Literal["selenium", "playwright", "obscura"] = "selenium",
# WITH:
        driver_type: Literal["selenium", "playwright", "obscura"] = "playwright",
```
**Why this shape**: single literal swap in the `__init__` signature; the
docstring above it (describing `driver_type`) already says "Browser
driver backend to use" with no hard-coded default mentioned, so it needs
no edit.

### `packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'driver_type: str = config.get("driver_type", "selenium")' packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py)
# REPLACE line 94:
        driver_type: str = config.get("driver_type", "selenium")
# WITH:
        driver_type: str = config.get("driver_type", "playwright")
```
**Why this shape**: single literal swap; the docstring above `create()`
(lines ~55-65) that says `driver_type` defaults to `"selenium"` should
also be updated to say `"playwright"` for accuracy — read the current
docstring text with `grep -n '"selenium"' packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py`
before editing and update any prose occurrence describing the default,
not just the code line.

### `packages/ai-parrot-tools/tests/scraping/test_toolkit_models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'assert config.driver_type == "selenium"' packages/ai-parrot-tools/tests/scraping/test_toolkit_models.py)
# REPLACE line 16 (inside TestDriverConfig.test_defaults):
        assert config.driver_type == "selenium"
# WITH:
        assert config.driver_type == "playwright"
```
Also add, inside `class TestDriverConfig` (after `test_defaults`):
```python
    def test_driver_config_defaults_to_playwright(self):
        """DriverConfig() with no driver_type arg defaults to playwright (FEAT-763)."""
        assert DriverConfig().driver_type == "playwright"
```
**Why**: `test_defaults` already asserts the full default set — fixing
its one line keeps it accurate; the new test documents the FEAT-763
behavior explicitly by name, matching spec §4's test list.

### `packages/ai-parrot-tools/tests/scraping/test_toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'assert toolkit._config.driver_type == "selenium"' packages/ai-parrot-tools/tests/scraping/test_toolkit.py)
# REPLACE line 121 (inside TestConstructor.test_default_config):
        assert toolkit._config.driver_type == "selenium"
# WITH:
        assert toolkit._config.driver_type == "playwright"
```
Also add, inside `class TestConstructor` (after `test_default_config`):
```python
    def test_web_scraping_toolkit_defaults_to_playwright(self, toolkit):
        """WebScrapingToolkit() with no driver_type arg defaults to playwright (FEAT-763)."""
        assert toolkit._config.driver_type == "playwright"
```
**Why**: same rationale as the `toolkit_models.py` edit above; the
`toolkit` fixture (already in this file, `test_toolkit.py:39-44`) never
passes `driver_type`, so it is the exact implicit-default construction
path.

### `packages/ai-parrot-tools/tests/scraping/test_driver_factory.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def test_default_creates_selenium' packages/ai-parrot-tools/tests/scraping/test_driver_factory.py)
# REPLACE lines 34-38:
    @patch("parrot.tools.scraping.drivers.selenium_driver.SeleniumDriver")
    def test_default_creates_selenium(self, mock_cls):
        mock_cls.return_value = MagicMock(spec=AbstractDriver)
        driver = DriverFactory.create()
        mock_cls.assert_called_once_with(browser="chrome", headless=True, auto_install=True, mobile=False)
        assert isinstance(driver, AbstractDriver)
# WITH:
    @patch("parrot.tools.scraping.drivers.playwright_driver.PlaywrightDriver")
    @patch("parrot.tools.scraping.drivers.playwright_config.PlaywrightConfig")
    def test_default_creates_playwright(self, mock_config, mock_cls):
        """DriverFactory.create() with no config defaults to Playwright (FEAT-763)."""
        mock_cls.return_value = MagicMock(spec=AbstractDriver)
        driver = DriverFactory.create()
        mock_config.assert_called_once()
        mock_cls.assert_called_once()
        assert isinstance(driver, AbstractDriver)
```
```python
# occurrences: 1 (verified: grep -c 'DriverFactory.create({"browser": "firefox", "headless": False})' packages/ai-parrot-tools/tests/scraping/test_driver_factory.py)
# REPLACE (inside test_dict_config_selenium):
        DriverFactory.create({"browser": "firefox", "headless": False})
# WITH:
        DriverFactory.create({"driver_type": "selenium", "browser": "firefox", "headless": False})
```
```python
# occurrences: 1 (verified: grep -c 'DriverFactory.create({"auto_install": False})' packages/ai-parrot-tools/tests/scraping/test_driver_factory.py)
# REPLACE (inside test_dict_config_auto_install):
        DriverFactory.create({"auto_install": False})
# WITH:
        DriverFactory.create({"driver_type": "selenium", "auto_install": False})
```
Also add, inside `class TestDriverFactoryCreate` (after the rewritten
`test_default_creates_playwright`):
```python
    @patch("parrot.tools.scraping.drivers.selenium_driver.SeleniumDriver")
    def test_driver_factory_create_explicit_selenium_still_works(self, mock_cls):
        """driver_type="selenium" still returns a SeleniumDriver after the default swap (FEAT-763)."""
        mock_cls.return_value = MagicMock(spec=AbstractDriver)
        driver = DriverFactory.create({"driver_type": "selenium"})
        mock_cls.assert_called_once()
        assert isinstance(driver, AbstractDriver)
```
**Why this shape**: the rename keeps `test_dict_config_selenium` /
`test_dict_config_auto_install` testing exactly what their names say
(selenium-specific dict forwarding) independent of which driver is now
the default; the new explicit test closes the "additive, not a removal"
acceptance criterion from spec §5. Note `test_selenium_explicit`
(`test_driver_factory.py:40-44`) already covers a similar case — the new
test is distinct in asserting the *mocked call itself* fires, matching
spec §4's exact test name.

### FILL IN checklist
*(none — every edit above is fully decided; no judgement calls remain)*

---

## Acceptance Criteria

- [ ] `DriverConfig()` (no args) has `driver_type == "playwright"`.
- [ ] `WebScrapingToolkit()` (no `driver_type` arg) has `._config.driver_type == "playwright"`.
- [ ] `DriverFactory.create()` (no args) and `DriverFactory.create({})` construct a `PlaywrightDriver`, not `SeleniumDriver`.
- [ ] `DriverFactory.create({"driver_type": "selenium"})` still constructs a `SeleniumDriver` (additive, not a removal).
- [ ] `parrot_tools.scraping.tool.WebScrapingTool`'s own default is untouched (its tests still pass unmodified).
- [ ] All tests in the Validation Commands below pass.
- [ ] `ruff check` clean on the three modified source files.

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/scraping/test_toolkit_models.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_toolkit.py -q`
- `pytest packages/ai-parrot-tools/tests/scraping/test_driver_factory.py -q`

---

## Test Specification

See the Implementation Blueprint above — every new/modified test body is
given verbatim there (spec §4's M1 test list: `test_driver_config_defaults_to_playwright`,
`test_web_scraping_toolkit_defaults_to_playwright`,
`test_driver_factory_dict_fallback_defaults_to_playwright` (covered by the
rewritten `test_default_creates_playwright`), `test_driver_factory_create_explicit_selenium_still_works`).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug browsing-playwright-default-and-screencast --feature-id FEAT-763`)
2. **Read the spec** at `sdd/specs/browsing-playwright-default-and-screencast.spec.md` for full context
3. **Check dependencies** — none (this is the first task)
4. **Verify the Codebase Contract** — before writing ANY code, re-run the
   `grep -c` commands in the Implementation Blueprint to confirm anchors
   have not drifted since this task was written
5. **Update status** in `sdd/tasks/index/browsing-playwright-default-and-screencast.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — apply the Implementation Blueprint edits exactly
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4839 browsing-playwright-default-and-screencast verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
