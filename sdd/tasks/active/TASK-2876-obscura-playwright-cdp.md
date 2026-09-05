# TASK-2876: Add Obscura CDP mode to PlaywrightDriver

**Feature**: FEAT-530 — Supervised Obscura Browser Integration
**Spec**: sdd/specs/obscura-new-browser-headless.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2875
**Assigned-to**: unassigned

## Context

Reuse Playwright's Chromium CDP client to connect to a supervised Obscura endpoint while preserving all current launch and cleanup behavior (spec Module 2).

## Scope

- Extend PlaywrightConfig with explicit Obscura/CDP connection settings.
- Make PlaywrightDriver.start() use chromium.connect_over_cdp() for Obscura mode and create the context/page expected by existing methods.
- Ensure quit() closes Playwright-owned resources without terminating an externally managed browser.
- Add unit tests for configuration, CDP connection, context/page setup, and cleanup ownership.

**NOT in scope**: DriverFactory dispatch, CLI, native MCP, Selenium, or PyO3.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py | MODIFY | Add Obscura/CDP settings while preserving current fields. |
| packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py | MODIFY | Add connect-over-CDP lifecycle branch. |
| packages/ai-parrot-tools/tests/scraping/test_playwright_config.py | MODIFY | Configuration coverage. |
| packages/ai-parrot-tools/tests/scraping/test_playwright_driver.py | MODIFY | Mocked CDP lifecycle coverage. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    from .abstract import AbstractDriver  # packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py:10
    from .playwright_config import PlaywrightConfig  # .../playwright_driver.py:11
    from dataclasses import dataclass  # .../playwright_config.py:3

### Existing Signatures to Use

    # packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py:10-52
    @dataclass
    class PlaywrightConfig: ...

    # packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_driver.py:15, 30-37, 41-105
    class PlaywrightDriver(AbstractDriver):
        def __init__(self, config: Optional[PlaywrightConfig] = None) -> None: ...
        async def start(self) -> None: ...
        async def quit(self) -> None: ...

### Does NOT Exist

- PlaywrightDriver.connect_obscura() — add the behavior through the existing lifecycle/configuration path.
- ObscuraDriver — reuse PlaywrightDriver.
- A Playwright Selenium bridge for Obscura.

## Implementation Notes

Follow the lazy playwright.async_api.async_playwright import and current context/page initialization. Use Chromium CDP because Obscura speaks CDP. Preserve ordinary Playwright launch and persistent-context branches in behavior. The manager's process ownership is separate from Playwright client ownership.

## Acceptance Criteria

- [ ] Obscura mode connects through chromium.connect_over_cdp().
- [ ] Existing navigation and driver methods see a valid default page/context.
- [ ] Ordinary Playwright launch and persistent-context modes remain functional.
- [ ] Cleanup does not stop an externally managed Obscura process.
- [ ] Focused Playwright tests pass.

## Test Specification

    def test_playwright_config_obscura_mode(): ...
    async def test_playwright_driver_connects_over_cdp(): ...
    async def test_playwright_driver_quit_does_not_close_external_browser_unless_owned(): ...

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
