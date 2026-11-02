---
id: FW-012
query_id: Q002
type: wiki_query
intent: "Aggregate: prior SDD specs that already designed the surfaces S-4 composes (pointers for the codebase lane and for the proposal's 'prior work')."
executed_at: 2026-10-30T15:25:30Z
duration_ms: 400
parent_id: null
depth: 1
---

# FW-012 — Prior specs behind each S-4 surface (seven features already shaped this ground)

## Summary

Each piece S-4 composes was specified separately: FEAT-573 `new-ui-cli-agents` (TASK-3413: `parrot agent --user/--token`, Q8 identity rule, TUI); FEAT-168 console CLI agents (`console-cli-agents.spec.md`, AgentREPL); FEAT-422/434 `agent-cli-daemon` (JSON-RPC/UDS, MCP stdio proxy; FEAT-434 added peercred identity); FEAT-485 `expose-toolkits-as-local-mcp` (per-toolkit stdio servers for Claude Code / Codex; FEAT-580 M4 lifecycle; TASK-2647 CLI); FEAT-262 `mcp-server-oauth2-support` (MCP client OAuth2 + Vault token storage); FEAT-477 `mcp-as-agent` (server-side principal guard + PBAC); FEAT-266/267 `o365-auth-homologation` (CLI device-code bootstrap, tenant sentinel); FEAT-696 `jiratoolkit-upgrades` (CLI 3LO auth, `oauth2_local`). None of them keys anything by a Navigator `user_id`, and only FEAT-477 (HTTP MCP) authenticates an MCP caller.

## Citations

- path: `sdd/specs/new-ui-cli-agents.spec.md`
  symbol: FEAT-573
  excerpt: |
    Agent Terminal Workspace for `parrot agent` — §3 Module 13 (TASK-3413 entry point, --user/--token, AC27)

- path: `sdd/specs/console-cli-agents.spec.md`
  symbol: FEAT-168
  excerpt: |
    Feature Specification: Console CLI Agents (AgentREPL)

- path: `sdd/specs/agent-cli-daemon.spec.md`
  symbol: FEAT-422
  excerpt: |
    Agent CLI Daemon — per-agent *Nix service with Rich console, JSON-RPC/UDS and MCP stdio proxy (Module 8 mcp_server.py)

- path: `sdd/specs/expose-toolkits-as-local-mcp.spec.md`
  symbol: FEAT-485
  excerpt: |
    Expose Toolkits as Local MCP — per-toolkit stdio servers for Claude Code / Codex

- path: `sdd/specs/mcp-server-oauth2-support.spec.md`
  symbol: FEAT-262
  excerpt: |
    MCP Server OAuth2 Support (MCPOAuth2Config, VaultMCPTokenStorage, HttpMCPSession._setup_oauth2)

- path: `sdd/tasks/index/mcp-as-agent.json`
  symbol: FEAT-477
  excerpt: |
    (per-spec index; TASK-2604 principal resolution + tenant binding, TASK-2605 PBAC guard)

- path: `sdd/specs/o365-auth-homologation.spec.md`
  symbol: FEAT-266
  excerpt: |
    O365 Auth Homologation — retire legacy interactive-auth + `device_code` broker kind (TASK-1685 CLI bootstrap)

- path: `sdd/specs/jiratoolkit-upgrades.spec.md`
  symbol: FEAT-696
  excerpt: |
    JiraToolkit upgrades — MCP parity, CLI 3LO auth, YAML knowledge base (M4 oauth2_local, M5 jira_cli)

## Notes

Wiki scores: `sdd/specs/console-cli-agents.spec.md` 0.64 (parent query, earlier session), `agent-cli-daemon.spec.md` 0.54, `expose-toolkits-as-local-mcp.spec.md` 0.14, `mcp-server-oauth2-support.spec.md` 0.21, `jiratoolkit-upgrades.spec.md` 0.95, `o365-auth-homologation.spec.md` 0.02, `TASK-3413` 1.00. Plan Q045/Q046 already read two of these; the codebase lane can skip re-locating them.
