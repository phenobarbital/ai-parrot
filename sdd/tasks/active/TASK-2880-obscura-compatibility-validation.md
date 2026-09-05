# TASK-2880: Validate Obscura Playwright and MCP compatibility

**Feature**: FEAT-530 — Supervised Obscura Browser Integration
**Spec**: sdd/specs/obscura-new-browser-headless.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2875, TASK-2876, TASK-2877, TASK-2878, TASK-2879
**Assigned-to**: unassigned

## Context

Exercise the complete supported surface against Obscura v0.2.2 on Linux and record pass, unsupported, and known-existing-gap results before the engine can be enabled broadly (spec Modules 6 and 8).

## Scope

- Add mocked unit coverage for final configuration and integration seams not covered by earlier tasks.
- Add an opt-in Linux Obscura fixture using the deterministic local fixture site and temporary ports/profiles.
- Exercise every AbstractDriver method and action currently covered by Playwright integration tests.
- Add scraping-plan, browsing-toolkit, native-MCP stdio, and WebAgent configuration integration coverage.
- Produce and document the compatibility matrix and current limitations.
- Document Linux/v0.2.2 prerequisites, lifecycle commands, MCP setup, and no-PyO3 scope.

**NOT in scope**: fixing Obscura engine incompatibilities discovered by the matrix, changing Selenium behavior, or embedding the Rust library.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot-tools/tests/scraping/test_driver_integration.py | MODIFY | Add Obscura feature-surface parity coverage. |
| packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py | MODIFY | Add opt-in Obscura fixture flow. |
| packages/ai-parrot-tools/tests/scraping/test_playwright_config.py | MODIFY | Final compatibility configuration checks. |
| packages/ai-parrot-tools/tests/scraping/test_playwright_driver.py | MODIFY | Final driver behavior checks. |
| tests/mcp/test_obscura_mcp.py | MODIFY | Native stdio interop coverage. |
| docs/ | CREATE or MODIFY | Compatibility matrix and operational documentation in the established docs location. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    from parrot.tools.scraping.drivers.abstract import AbstractDriver  # packages/ai-parrot-tools/tests/scraping/test_driver_integration.py:13
    from parrot.tools.scraping.driver_factory import DriverFactory  # .../test_driver_integration.py:14
    from parrot.tools.scraping.executor import execute_plan_steps  # .../test_fixture_site_integration.py:17
    from parrot.tools.scraping.plan import ScrapingPlan  # .../test_fixture_site_integration.py:18

### Existing Signatures to Use

    # packages/ai-parrot-tools/src/parrot_tools/scraping/drivers/abstract.py:11-180
    class AbstractDriver(ABC):
        async def start(self) -> None: ...
        async def quit(self) -> None: ...
        async def navigate(self, url: str, timeout: int = 30) -> None: ...
        async def click(self, selector: str, timeout: int = 10) -> None: ...
        async def fill(self, selector: str, value: str, timeout: int = 10) -> None: ...
        async def screenshot(self, path: str, full_page: bool = False) -> bytes: ...

    # packages/ai-parrot-tools/tests/scraping/test_fixture_site_integration.py
    execute_plan_steps(driver, plan=..., credential_resolver=...)

### Does NOT Exist

- A checked-in Obscura binary fixture; integration tests require an operator-provided Linux v0.2.2 binary or skip cleanly.
- A compatibility result that can be assumed from CDP protocol compatibility.
- Native PyO3 embedding or a Rust library test harness.

## Implementation Notes

Reuse the existing local fixture and real Playwright driver fixtures. Mark external-binary tests explicitly and keep ordinary test runs deterministic. The matrix must retain current known gaps around cookies, selected waits, file upload, and downloads rather than treating them as unexplained failures.

## Acceptance Criteria

- [ ] Matrix enumerates all AbstractDriver methods and current Playwright integration actions.
- [ ] Each capability is recorded as pass, unsupported, or known-existing-gap with evidence.
- [ ] Opt-in Linux/v0.2.2 fixture covers representative scraping and browsing flows.
- [ ] Native MCP initialize/list/call interop is verified over stdio.
- [ ] Documentation covers prerequisites, CLI lifecycle, MCP setup, and limitations.
- [ ] Existing scraping, browsing, Playwright, Selenium, and MCP tests pass.

## Test Specification

    async def test_obscura_playwright_fixture_site(): ...
    async def test_obscura_scraping_plan_driver_parity(): ...
    async def test_obscura_browsing_toolkit_catalog_flow(): ...
    async def test_obscura_native_mcp_stdio_interop(): ...
    async def test_obscura_webagent_configuration(): ...

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
