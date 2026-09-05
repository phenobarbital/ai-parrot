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

### Verified Imports

    import logging  # packages/ai-parrot-server/src/parrot/mcp/chrome.py:1
    import socket  # packages/ai-parrot-server/src/parrot/mcp/chrome.py:2
    import subprocess  # packages/ai-parrot-server/src/parrot/mcp/chrome.py:3
    import requests  # packages/ai-parrot-server/src/parrot/mcp/chrome.py:7

### Existing Signatures to Use

    # packages/ai-parrot-server/src/parrot/mcp/chrome.py:8-14
    class ChromeManager:
        def __init__(self, port: int = 9222, logger: logging.Logger | None = None): ...
        def is_port_open(self, host: str, port: int) -> bool: ...
        def is_chrome_running(self) -> bool: ...
        def start(self, headless: bool = True) -> bool: ...
        def stop(self): ...

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

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
