# TASK-2878: Register the native Obscura MCP server

**Feature**: FEAT-530 — Supervised Obscura Browser Integration
**Spec**: sdd/specs/obscura-new-browser-headless.spec.md
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2875
**Assigned-to**: unassigned

## Context

Make Obscura's native obscura mcp stdio server available to Codex and AI-Parrot agents while retaining Chrome DevTools MCP as a separate option (spec Module 4).

## Scope

- Add a factory/helper that builds an MCPServerConfig for obscura mcp.
- Forward binary path, version, port, stealth, private-network, and environment settings according to the Obscura CLI contract.
- Register the capability through existing agent MCP configuration paths.
- Add configuration and tool-discovery tests that keep JSON-RPC stdout clean.

**NOT in scope**: replacing Chrome DevTools MCP, implementing Obscura MCP tools, process-manager implementation, CLI, or PyO3.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| packages/ai-parrot/src/parrot/mcp/integration.py | MODIFY | Add native Obscura stdio configuration factory. |
| packages/ai-parrot/src/parrot/bots/chrome.py | MODIFY if agent configuration requires it | Select Obscura MCP without changing Chrome defaults. |
| tests/mcp/test_obscura_mcp.py | CREATE | Command construction and stdio interop tests. |

## Codebase Contract (Anti-Hallucination)

### Verified Imports

    from parrot.mcp.integration import MCPServerConfig  # packages/ai-parrot/src/parrot/mcp/integration.py:22-26

### Existing Signatures to Use

    # packages/ai-parrot/src/parrot/mcp/integration.py:1105-1118
    def create_chrome_devtools_mcp_server(..., **kwargs) -> MCPServerConfig: ...

    # packages/ai-parrot/src/parrot/mcp/integration.py:1348
    async def add_mcp_server(self, config: MCPServerConfig) -> List[str]: ...

    # packages/ai-parrot/src/parrot/mcp/integration.py:22-26
    MCPServerConfig = MCPClientConfig

### Does NOT Exist

- create_obscura_mcp_server — proposed new helper.
- An Obscura entry in the current MCP server catalog.
- An AI-Parrot implementation of Obscura's browser tool schema.

## Implementation Notes

Mirror the existing stdio factory and agent registration conventions. Treat the Obscura executable as the command and keep protocol output on stdout. Do not make Chrome DevTools MCP behavior depend on Obscura availability.

## Acceptance Criteria

- [ ] Factory produces the correct obscura mcp stdio command and arguments.
- [ ] Codex/agent setup can discover and call the native server.
- [ ] Chrome DevTools MCP defaults remain unchanged.
- [ ] MCP unit and interop tests pass.

## Test Specification

    def test_create_obscura_mcp_server_args(): ...
    async def test_obscura_native_mcp_stdio_interop(): ...
    async def test_obscura_webagent_configuration(): ...

## Completion Note

**Completed by**: sdd-worker (Sonnet)
**Date**: 2026-09-05
**Notes**: Added `create_obscura_mcp_server()` to
`packages/ai-parrot/src/parrot/mcp/integration.py` — a pure config
builder (mirrors `create_chrome_devtools_mcp_server`'s "does not start
anything" contract) producing `MCPServerConfig(command=binary_path or
"obscura", args=["mcp", "--port", str(port), ...stealth/private-network
flags], transport="stdio")`. Added `MCPEnabledMixin.add_obscura_mcp_server()`
mirroring `add_chrome_devtools_mcp_server`'s registration pattern, but
WITHOUT an `ensure_running`-style pre-start step: unlike Chrome DevTools
MCP (which attaches to a *separately* running browser via
`--browser-url`), Obscura's native MCP mode is self-contained — the
`obscura mcp` subprocess is spawned and supervised by the MCP transport
layer itself (`StdioMCPSession._start_process`), not by AI-Parrot.
Process supervision for the *separate* CDP (`obscura serve`) mode stays
entirely with TASK-2875's `ObscuraProcessManager` — unrelated to this
native MCP path. Added `ObscuraMCPConfig` + an opt-in `obscura_config`
parameter to `WebAgent` (`packages/ai-parrot/src/parrot/bots/chrome.py`):
when set, `configure()` also calls `add_obscura_mcp_server()` alongside
(never instead of) the existing unconditional
`add_chrome_devtools_mcp_server()` call, so Chrome DevTools MCP defaults
are unaffected whether or not Obscura is configured. Used
`getattr(self, "obscura_config", None)` in `configure()` (not a direct
attribute access) specifically because an existing test in
`packages/ai-parrot/tests/bots/test_chrome.py` (out of this task's file
list, intentionally left untouched) constructs `WebAgent` via
`WebAgent.__new__(WebAgent)` + manual attribute assignment, bypassing
`__init__` entirely — a direct `self.obscura_config` access would have
raised `AttributeError` on that pre-existing test and was caught by
running it, not assumed. New tests in `tests/mcp/test_obscura_mcp.py`
(CREATE, the only test file this task's table lists) cover: the config
factory's default/custom/flag-toggling args; a stdio interop test that
drives a mocked `obscura mcp` subprocess through
`StdioMCPSession.connect()`/`list_tools()` — including a stray non-JSON
stdout line the client must skip rather than choke on, and asserts every
line written to the child's stdin is valid JSON; and `WebAgent`
configuration tests confirming Obscura tools are registered alongside
Chrome DevTools MCP when opted in, and not at all otherwise. Full
`packages/ai-parrot/tests/bots/test_chrome.py` suite re-run: 57 passed,
same pre-existing 5 failures as an unmodified checkout (verified
byte-for-byte against the main repo, all `GoogleGenAIClient` import
environment issue, unrelated to this feature) — confirms no regression.
Note: this worktree initially lacked the compiled `parrot.utils.types`/
`parrot.utils.parsers.toml` Cython extensions (`.so`, gitignored build
artifacts) needed to import `parrot.bots.agent` at all; copied them in
from the main checkout's matching `cpython-312` build to run these
tests — no repo files were affected (verified via `git status
--ignored`). ruff clean on all 3 changed/created files (integration.py's
3 pre-existing, unrelated lint findings reproduced identically via `git
stash`).
**Deviations from spec**: none — `create_obscura_mcp_server()` matches
the spec's proposed signature (`binary_path`, `stealth`, `port`,
`**kwargs`) plus `name`/`allow_private_network`/`env`, all named directly
in the spec's Module 4 responsibility text ("Forward binary path,
version, port, stealth, private-network, and environment settings").
`version` was intentionally NOT added as a CLI flag: no verified
`obscura mcp` CLI flag for it exists in the Codebase Contract, and
`ObscuraProcessManager` (TASK-2875) already owns the pinned-v0.2.2
concern for the CDP-serving process — inventing an unverified flag here
would violate the anti-hallucination contract.
