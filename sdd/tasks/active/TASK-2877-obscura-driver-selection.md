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

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
