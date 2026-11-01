---
id: F045
query_id: Q001
type: wiki_query
intent: "Aggregate: existing test files for the CLI, mcp-local, agentd, MCP OAuth and principal-guard surfaces (from Q001–Q006 result sets)."
executed_at: 2026-10-30T15:25:00Z
duration_ms: 500
parent_id: null
depth: 1
merged_from: [FW-011]
---

# F045 — Test coverage map for the S-4 surfaces (from wiki result sets)

## Summary

The wiki surfaced tests on every surface S-4 touches, in four test trees: `packages/ai-parrot/tests/cli/` (21 entries; `test_identity.py` tenant sentinel, `test_agent_command.py` CliRunner for `parrot agent` incl. `--user`/`--token` rules, `test_integration.py` AgentREPL send/session), `packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py` (device-code e2e, WorkIQ OBO interop), `packages/ai-parrot/tests/mcp/{test_local_server,test_local_server_concurrency}.py` + root `tests/mcp/test_local_cli.py` (serve path) + root `tests/mcp/test_oauth2_e2e.py` (Vault token storage round trip, FEAT-262), `packages/ai-parrot-integrations/tests/agentd/{test_proxy,test_mcp_proxy,test_e2e}.py` (MCP stdio handshake against a real daemon), `packages/ai-parrot-server/tests/mcp/test_principal_resolution.py` (FEAT-477), and `packages/ai-parrot-tools/tests/unit/test_oauth2_local_wiring.py` (fixed local identity, channel guard). Two trees for MCP tests (root `tests/mcp` vs package `tests/mcp`) — same two-tree gotcha as the wiki tests.

## Citations

- path: `packages/ai-parrot/tests/cli/test_identity.py`
  symbol: module
  excerpt: |
    Unit tests for the CLI identity bootstrap's tenant_id resolution (FEAT-267).
- path: `packages/ai-parrot/tests/cli/test_agent_command.py`
  symbol: module
  excerpt: |
    CliRunner tests for the `parrot agent` entry point (FEAT-573 AC1/AC2/AC22/AC27).
- path: `packages/ai-parrot/tests/cli/test_integration.py`
  symbol: `TestAgentREPLSend`
  excerpt: |
    Integration tests for AgentREPL send() and history tracking.
- path: `packages/ai-parrot/tests/integration/test_cli_devicecode_e2e.py`
  symbol: `test_cli_device_code_end_to_end` / `test_devicecode_token_consumable_by_workiq_obo`
  excerpt: |
    End-to-end integration tests for the O365 device-code CLI flow (FEAT-266).
- path: `tests/mcp/test_local_cli.py`
  symbol: `test_serve_path_stub_toolkit`
  excerpt: |
    Serve path resolves the stub toolkit and drives server.start().
- path: `packages/ai-parrot/tests/mcp/test_local_server.py`
  symbol: module
  excerpt: |
    (StdioMCPServer tests; sibling test_local_server_concurrency.py)
- path: `tests/mcp/test_oauth2_e2e.py`
  symbol: `TestVaultMCPTokenStorageRoundTrip`
  excerpt: |
    End-to-end integration tests for MCP OAuth2 support (FEAT-262, TASK-1666).
- path: `packages/ai-parrot-integrations/tests/agentd/test_e2e.py`
  symbol: `TestEndToEnd.test_mcp_stdio_ask_agent`
  excerpt: |
    AC: MCP handshake over stdio-handler calls + `ask_agent` against a real daemon.
- path: `packages/ai-parrot-server/tests/mcp/test_principal_resolution.py`
  symbol: module
  excerpt: |
    Unit tests for principal resolution + tenant binding (FEAT-477, TASK-2604).
- path: `packages/ai-parrot-tools/tests/unit/test_oauth2_local_wiring.py`
  symbol: `TestOAuth2LocalMode.test_toolkit_runs_without_permission_context`
  excerpt: |
    Local mode resolves the CLI token without a permission context.

## Notes

Wiki ids: `dir:packages/ai-parrot/tests/cli` (0.35), `dir:tests/mcp` (0.27), `dir:packages/ai-parrot-server/tests/mcp` (0.11), plus the per-file hits listed in FW-001/002/003/005/006/008/009. Confirms plan Q025's glob should also cover root `tests/mcp/` and `packages/ai-parrot-tools/tests/unit/`.
[cross-lane: type=glob, intent=extend Q025 to tests/mcp/test_*.py and packages/ai-parrot-tools/tests/unit/test_oauth2_local_wiring.py]
[citation-check: missing] packages/ai-parrot/tests/cli/test_identity.py, tests/cli/test_agent_command.py, tests/mcp/test_local_server.py — symbol `module` is a label, not a code symbol; files exist (probes c125, c126, c130)
