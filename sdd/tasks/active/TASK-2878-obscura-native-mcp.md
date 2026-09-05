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

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
