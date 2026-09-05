# TASK-2875: Implement supervised Obscura process management

**Feature**: FEAT-530 — Supervised Obscura Browser Integration
**Spec**: sdd/specs/obscura-new-browser-headless.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement the Linux Obscura process and configuration foundation required by the Playwright CDP and native MCP integrations (spec sections 2–3, Module 1).

## Scope

- Add validated configuration for the Obscura v0.2.2 Linux binary, host, CDP port, stealth, and private-network option.
- Implement asynchronous start, CDP readiness probing, status, and stop operations.
- Track process ownership so adopted or externally managed processes are never terminated by the manager.
- Add unit tests for defaults, readiness, ownership, missing binaries, and timeout failures.

**NOT in scope**: Playwright driver changes, MCP registration, CLI commands, PyO3 bindings, or Selenium changes.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot-server/src/parrot/mcp/obscura.py | CREATE | Configuration and supervised process manager. |
| packages/ai-parrot-server/tests/mcp/test_obscura.py | CREATE | Mocked lifecycle and readiness tests. |

## Codebase Contract (Anti-Hallucination)

> **Corrected 2026-09-05 (sdd-worker, TASK-2875)**: the contract below was
> stale. `ChromeManager` is fully async (`aiohttp` readiness probe,
> `asyncio.subprocess` lifecycle) — not the sync `socket`/`subprocess`/
> `requests` shape originally described. Verified against
> `packages/ai-parrot-server/src/parrot/mcp/chrome.py` as it exists on
> `dev` at implementation time.

### Verified Imports

    import asyncio  # packages/ai-parrot-server/src/parrot/mcp/chrome.py:1
    import logging  # packages/ai-parrot-server/src/parrot/mcp/chrome.py:2
    import shutil  # packages/ai-parrot-server/src/parrot/mcp/chrome.py:3
    import aiohttp  # packages/ai-parrot-server/src/parrot/mcp/chrome.py:6

### Existing Signatures to Use

    # packages/ai-parrot-server/src/parrot/mcp/chrome.py:9-159
    class ChromeManager:
        def __init__(self, port: int = 9222, logger: logging.Logger | None = None) -> None: ...  # :27-37
        async def is_running(self) -> bool: ...  # :39-58, aiohttp GET /json/version, 1s timeout
        async def is_chrome_running(self) -> bool: ...  # :60-76, DEPRECATED alias for is_running()
        async def start(self, headless: bool = True, timeout: float = 10.0) -> bool: ...  # :78-143
        async def stop(self) -> None: ...  # :145-159, terminate() then wait_for(5s) else kill()

### Does NOT Exist

- parrot.mcp.obscura.ObscuraProcessManager — proposed new component.
- An Obscura binary or repository dependency — verify the configured executable at runtime.
- A native PyO3 Obscura binding.

## Implementation Notes

Follow ChromeManager for socket probing, subprocess lifecycle, logging, and bounded readiness waits, while correcting its synchronous API and ownership semantics for this feature. Keep MCP stdio process construction separate from CDP browser ownership. Avoid adding dependencies beyond the existing package constraints.

## Acceptance Criteria

- [ ] Linux/v0.2.2 configuration validates binary and port settings.
- [ ] Start waits for a responsive CDP endpoint and returns actionable failure information.
- [ ] Stop terminates only a process started by this manager.
- [ ] Unit tests pass for success, missing binary, timeout, adoption, and ownership cases.

## Test Specification

    def test_obscura_config_defaults(): ...
    async def test_obscura_manager_start_waits_for_cdp(): ...
    async def test_obscura_manager_stop_only_terminates_owned_process(): ...
    async def test_obscura_manager_start_failure(): ...

## Agent Instructions

Read the full spec and re-verify this contract before implementation. Keep the implementation limited to this task and leave the task file active until verification is complete.

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-09-05
**Notes**: Implemented `ObscuraProcessConfig` (validated binary/port/host/
stealth/allow_private_network/attach_only/startup_timeout) and
`ObscuraProcessManager` (async `is_running`/`start`/`stop`/`status`) in
`packages/ai-parrot-server/src/parrot/mcp/obscura.py`, following the
current async `ChromeManager` pattern (aiohttp readiness probe,
`asyncio.subprocess` lifecycle). Added an explicit `attach_only` mode so an
externally managed endpoint can be adopted without ever being terminated
by `stop()` — ownership is tracked via `_owns_process` and only set when
this manager itself spawns the process. The task's Codebase Contract was
stale (described a synchronous `ChromeManager` with `socket`/`subprocess`/
`requests`); corrected in place against the actual async file before
implementing, per Cardinal Rule 4. 6 unit tests in
`packages/ai-parrot-server/tests/mcp/test_obscura.py` cover defaults,
successful start-and-own, stop-only-if-owned (including attach_only
never-owns), missing-binary failure, readiness-timeout failure (with
spawn cleanup), attach_only-without-endpoint failure, and status
reporting — all pass; ruff clean.
**Deviations from spec**: none — `ObscuraProcessConfig`/
`ObscuraProcessManager` field/method names match the spec's proposed
interfaces exactly. `attach_only` is an additive field (spec explicitly
left exact field names open) implementing the spec's required "adopted
only via explicit attach-only mode" semantics.
