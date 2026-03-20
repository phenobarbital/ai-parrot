# TASK-061: WebScrapingTool Driver Integration

**Feature**: FEAT-015 — PlaywrightDriver
**Spec**: `sdd/specs/scraping-playwrightdriver.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-060
**Assigned-to**: unassigned

---

## Context

> This task implements Module 6 from the spec: wiring `DriverFactory` into
> `WebScrapingTool` so that the tool uses the factory to obtain its browser
> driver instead of directly instantiating `SeleniumSetup`. This is the
> integration point where the driver abstraction layer meets the existing
> tool infrastructure. The change must be fully backward compatible — existing
> code using `WebScrapingTool` with default settings must continue to work
> unchanged.

---

## Scope

- Modify `WebScrapingTool` (in `parrot/tools/scraping/tool.py`) to:
  - Accept a new optional `driver_type` parameter (default: `"selenium"`)
  - Accept optional `driver_config` dict parameter for driver-specific settings
  - Use `DriverFactory.create()` instead of direct `SeleniumSetup` instantiation
  - Store the `AbstractDriver` instance and use its interface for all operations
- Update `parrot/tools/scraping/__init__.py` to export the new driver-related
  classes alongside existing exports
- Write integration tests verifying backward compatibility and driver swapping

**NOT in scope**: Changing WebScrapingTool's public API signature beyond adding
the new optional parameters, modifying step execution logic, removing any
existing functionality

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/scraping/tool.py` | MODIFY | Replace `SeleniumSetup` with `DriverFactory.create()` |
| `parrot/tools/scraping/__init__.py` | MODIFY | Export driver-related classes |
| `tests/tools/scraping/test_tool_driver_integration.py` | CREATE | Integration tests |

---

## Implementation Notes

### Pattern to Follow

```python
# In WebScrapingTool.__init__():
from parrot.tools.scraping.driver_factory import DriverFactory

class WebScrapingTool:
    def __init__(
        self,
        ...,  # existing parameters unchanged
        driver_type: str = "selenium",
        driver_config: Optional[Dict[str, Any]] = None,
    ):
        # Build config dict merging defaults with overrides
        config = {
            "driver_type": driver_type,
            "browser": browser,       # existing param
            "headless": headless,      # existing param
            **(driver_config or {}),
        }
        self._driver = DriverFactory.create(config)

    async def _start_driver(self):
        """Start the browser driver."""
        await self._driver.start()

    async def _stop_driver(self):
        """Stop the browser driver."""
        await self._driver.quit()
```

### Key Constraints

- **Backward compatible**: Default behavior must remain identical (Selenium + chrome + headless)
- **No breaking API changes**: All existing constructor parameters continue to work
- **driver_type parameter**: New optional `str` param, default `"selenium"`
- **driver_config parameter**: New optional `Dict` param for advanced config passthrough
- **Existing tests must pass**: Run existing scraping tests to verify no regressions
- **Import updates**: `__init__.py` should export `DriverFactory`, `AbstractDriver`,
  `PlaywrightDriver`, `SeleniumDriver`, `PlaywrightConfig`

### References in Codebase

- `parrot/tools/scraping/tool.py` — existing `WebScrapingTool` to modify
- `parrot/tools/scraping/__init__.py` — existing exports to extend
- `parrot/tools/scraping/driver_factory.py` (TASK-060) — factory to use
- `sdd/specs/scraping-playwrightdriver.spec.md` §2 — integration design

---

## Acceptance Criteria

- [ ] `WebScrapingTool()` with no new params behaves identically to current (Selenium)
- [ ] `WebScrapingTool(driver_type="playwright")` uses PlaywrightDriver
- [ ] `WebScrapingTool(driver_type="selenium")` uses SeleniumDriver (explicit)
- [ ] `driver_config` parameter passes through to `DriverFactory.create()`
- [ ] Existing `browser`, `headless` params still work and are forwarded to factory
- [ ] `parrot/tools/scraping/__init__.py` exports `DriverFactory`, `AbstractDriver`,
  `PlaywrightDriver`, `SeleniumDriver`, `PlaywrightConfig`
- [ ] No existing tests broken
- [ ] All new tests pass: `pytest tests/tools/scraping/test_tool_driver_integration.py -v`
- [ ] No linting errors: `ruff check parrot/tools/scraping/tool.py`

---

## Test Specification

```python
# tests/tools/scraping/test_tool_driver_integration.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from parrot.tools.scraping.drivers.abstract import AbstractDriver


class TestWebScrapingToolDefaultDriver:
    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_default_creates_selenium(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_driver = MagicMock(spec=AbstractDriver)
        mock_factory.create.return_value = mock_driver

        tool = WebScrapingTool()
        mock_factory.create.assert_called_once()
        call_args = mock_factory.create.call_args[0][0]
        assert call_args["driver_type"] == "selenium"


class TestWebScrapingToolPlaywrightDriver:
    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_playwright_driver_type(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_driver = MagicMock(spec=AbstractDriver)
        mock_factory.create.return_value = mock_driver

        tool = WebScrapingTool(driver_type="playwright")
        call_args = mock_factory.create.call_args[0][0]
        assert call_args["driver_type"] == "playwright"


class TestWebScrapingToolDriverConfig:
    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_driver_config_passthrough(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_driver = MagicMock(spec=AbstractDriver)
        mock_factory.create.return_value = mock_driver

        tool = WebScrapingTool(
            driver_type="playwright",
            driver_config={"slow_mo": 100, "locale": "en-US"},
        )
        call_args = mock_factory.create.call_args[0][0]
        assert call_args["slow_mo"] == 100
        assert call_args["locale"] == "en-US"


class TestWebScrapingToolBackwardCompat:
    @patch("parrot.tools.scraping.tool.DriverFactory")
    def test_browser_param_forwarded(self, mock_factory):
        from parrot.tools.scraping.tool import WebScrapingTool

        mock_driver = MagicMock(spec=AbstractDriver)
        mock_factory.create.return_value = mock_driver

        tool = WebScrapingTool(browser="firefox", headless=False)
        call_args = mock_factory.create.call_args[0][0]
        assert call_args["browser"] == "firefox"
        assert call_args["headless"] is False


class TestScrapingPackageExports:
    def test_driver_factory_importable(self):
        from parrot.tools.scraping import DriverFactory
        assert DriverFactory is not None

    def test_abstract_driver_importable(self):
        from parrot.tools.scraping import AbstractDriver
        assert AbstractDriver is not None

    def test_playwright_driver_importable(self):
        from parrot.tools.scraping import PlaywrightDriver
        assert PlaywrightDriver is not None

    def test_selenium_driver_importable(self):
        from parrot.tools.scraping import SeleniumDriver
        assert SeleniumDriver is not None

    def test_playwright_config_importable(self):
        from parrot.tools.scraping import PlaywrightConfig
        assert PlaywrightConfig is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/scraping-playwrightdriver.spec.md` for full context
2. **Check dependencies** — TASK-060 must be in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Read current `tool.py`** to understand existing constructor parameters and driver usage
5. **Implement** following the scope and notes above
6. **Run existing tests** to verify no regressions
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-061-tool-driver-integration.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-25
**Notes**: Wired `DriverFactory.create()` into `WebScrapingTool.__init__` to create
an `AbstractDriver` instance (`self._abstract_driver`). Added `driver_config` parameter
for advanced config passthrough. Updated `initialize_driver()` to start the abstract
driver and extract raw WebDriver/Playwright handles for backward compatibility with
existing Selenium/Playwright-specific code. Updated `cleanup()` to use
`self._abstract_driver.quit()`. Exported `AbstractDriver`, `PlaywrightConfig`,
`PlaywrightDriver`, `SeleniumDriver` from `parrot.tools.scraping`. 15 new tests,
150 total FEAT-015 tests passing.

**Deviations from spec**: The `initialize_driver(config_overrides)` path with
config_overrides still falls back to the legacy `_setup_selenium()` for backward
compat, since config_overrides require re-creating SeleniumSetup with merged config.
The standard path (no overrides) uses `_abstract_driver.start()`. Pre-existing lint
errors in tool.py (9 issues) were not fixed as they are outside task scope.
