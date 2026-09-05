# TASK-2879: Add Obscura lifecycle CLI commands

**Feature**: FEAT-530 — Supervised Obscura Browser Integration
**Spec**: sdd/specs/obscura-new-browser-headless.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2875
**Assigned-to**: unassigned

## Context

Users need explicit AI-Parrot commands to start, stop, and inspect the supervised Obscura process, with an MCP configuration operation aligned to existing CLI conventions (spec Module 5).

## Scope

- Add lazy CLI registration for Obscura start, stop, and status operations.
- Delegate lifecycle work to ObscuraProcessManager rather than duplicating subprocess logic.
- Provide the CLI/configuration path needed to launch the native obscura mcp server.
- Report actionable errors and status while preserving current command loading behavior.
- Add CLI delegation tests.

**NOT in scope**: browser-driver implementation, MCP tool implementation, Selenium, or PyO3.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot/src/parrot/cli/commands.py | MODIFY | Add lifecycle command definitions/registration. |
| packages/ai-parrot/src/parrot/cli/__init__.py | MODIFY if registration requires it | Preserve lazy command loading. |
| packages/ai-parrot-server/src/parrot/mcp/obscura.py | MODIFY if CLI adapter belongs beside manager | Expose command-facing lifecycle adapter only. |
| tests/cli/test_obscura.py | CREATE | CLI delegation and error reporting tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    from parrot.mcp.obscura import ObscuraProcessManager  # proposed import created by TASK-2875

### Existing Signatures to Use

    # packages/ai-parrot/src/parrot/cli/commands.py
    # Verify the current lazy command registration and callback signatures before editing.

    # packages/ai-parrot-server/src/parrot/mcp/chrome.py:8-14, 38-42, 93-105
    class ChromeManager:
        def __init__(self, port: int = 9222, logger: logging.Logger | None = None): ...
        def start(self, headless: bool = True) -> bool: ...
        def stop(self): ...

### Does NOT Exist

- Obscura CLI commands or command names in AI-Parrot.
- parrot.mcp.obscura.ObscuraProcessManager until TASK-2875 is complete.
- A second CLI framework for browser process management.

## Implementation Notes

Use the actual command registration mechanism found in commands.py; the file list is intentionally bounded but callback placement may follow the existing lazy-module pattern. Never launch Chrome/Selenium as a fallback when Obscura is selected.

## Acceptance Criteria

- [ ] Start, stop, and status commands delegate to the manager.
- [ ] CLI reports readiness and failure states clearly.
- [ ] Native MCP launch is available through the documented command/config path.
- [ ] Existing CLI tests remain green.

## Test Specification

    def test_obscura_cli_lifecycle(): ...
    def test_obscura_cli_reports_start_failure(): ...

## Completion Note

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
