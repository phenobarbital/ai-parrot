# TASK-2877: Select Obscura through the existing driver factory

**Feature**: FEAT-530 — Supervised Obscura Browser Integration
**Spec**: sdd/specs/obscura-new-browser-headless.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2876
**Assigned-to**: unassigned

## Context

Expose Obscura as a configuration option that returns the existing PlaywrightDriver in CDP mode, keeping toolkit callers browser-neutral (spec Module 3).

## Scope

- Extend DriverFactory.create() normalization and dispatch for an Obscura engine configuration.
- Pass all required CDP/process settings into PlaywrightConfig.
- Preserve default Selenium behavior and ordinary Playwright browser mapping.
- Extend factory tests and verify representative toolkit configuration plumbing only where required.

**NOT in scope**: process implementation, MCP registration, CLI, or Selenium bridge.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py | MODIFY | Dispatch Obscura configuration to Playwright CDP mode. |
| packages/ai-parrot-tools/src/parrot_tools/scraping/toolkit.py | MODIFY if required | Carry engine settings without driver-specific branching. |
| packages/ai-parrot-tools/tests/scraping/test_driver_factory.py | MODIFY | Factory and backward-compatibility tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    from .drivers.abstract import AbstractDriver  # packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py:13
    from .drivers.playwright_config import PlaywrightConfig  # imported lazily in driver_factory.py:77-80
    from .drivers.playwright_driver import PlaywrightDriver  # imported lazily in driver_factory.py:81-83

### Existing Signatures to Use

    # packages/ai-parrot-tools/src/parrot_tools/scraping/driver_factory.py:31-46
    class DriverFactory:
        @staticmethod
        def create(config: Optional[Union[Dict[str, Any], Any]] = None) -> AbstractDriver: ...

    # packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/playwright_config.py:10
    @dataclass
    class PlaywrightConfig: ...

### Does NOT Exist

- ObscuraDriver or a separate Obscura abstract-driver implementation.
- An existing engine=obscura factory branch.
- A Selenium configuration that accepts an Obscura CDP endpoint.

## Implementation Notes

Keep DriverFactory.create() synchronous and return an unstarted driver, matching its current contract. Do not alter the default driver_type=selenium path. Obscura should be explicit and must not silently fall back to Chrome.

## Acceptance Criteria

- [ ] Obscura configuration returns PlaywrightDriver with CDP settings.
- [ ] Selenium and ordinary Playwright factory tests remain green.
- [ ] Toolkit consumers do not require Obscura-specific branches.

## Test Specification

    def test_factory_creates_obscura_playwright_driver(): ...
    def test_factory_preserves_selenium_and_playwright_launch_modes(): ...

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-09-05
**Notes**: Added a `driver_type == "obscura"` branch to
`DriverFactory.create()` that builds a `PlaywrightConfig(engine="obscura",
browser_type="chromium", ...)` (forwarding `cdp_endpoint_url`,
`obscura_binary`, `obscura_port`, `obscura_stealth`,
`obscura_allow_private_network` plus the usual viewport/locale/timezone/
proxy/timeout options) and returns it wrapped in `PlaywrightDriver`,
exactly mirroring the existing `"playwright"` branch's structure.
`browser` is intentionally ignored for Obscura — `browser_type` is always
forced to `"chromium"` since Obscura only speaks CDP as a
Chromium-compatible engine, so it can never silently fall back to
launching a local Chrome/Chromium. The `"selenium"`/`"playwright"`
branches and the default `driver_type` are untouched; the unknown-type
error message now lists `'obscura'`. `toolkit.py` required **no** change:
its `WebScrapingTool.__init__` already merges `driver_config` overrides
into `factory_config` before calling `DriverFactory.create()`
(`packages/ai-parrot-tools/src/parrot_tools/scraping/tool.py:362-371`),
so `obscura_*`/`cdp_endpoint_url` keys pass through generically —
verified this pass-through exists rather than guessing, per the task's
"MODIFY if required" wording (`WebScrapingToolkit`'s separate
`DriverRegistry`-based session path in `driver_context.py`/
`toolkit_models.py` was intentionally left untouched — it is not in this
task's file list or Codebase Contract). New tests: obscura config
forwarding, forced-chromium-ignoring-`browser`, and an explicit
selenium+playwright preservation test. All 49 factory/integration tests
pass; full `scraping/` suite: 838 passed (7 pre-existing failures in
`test_toolkit_integration.py` confirmed unrelated — missing FEAT-013
`CrawlEngine` dependency, reproduced identically on `git stash`); ruff
clean.
**Deviations from spec**: none — reuses `PlaywrightConfig`/
`PlaywrightDriver` per the spec's "Does NOT Exist" constraint (no
`ObscuraDriver`).
