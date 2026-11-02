---
id: F032
query_id: Q046
type: read
intent: "agent-cli-daemon spec design"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-032]
---

# F032 — agentd spec: UDS JSON-RPC authenticated by filesystem permissions; clients attach/ask/mcp-serve; DaemonAgentProxy mirrors ServerAgentProxy

## Summary

The agentd spec states the daemon is 'authenticated by filesystem permissions' (UDS), exposes `parrot attach`, `parrot ask`, `parrot mcp-serve <name>` (StdioMCPServer proxying tools to the daemon via `AgentDaemonClient`), and that `DaemonAgentProxy` mirrors `ServerAgentProxy`'s duck-typed loader interface so `AgentREPL` is reused verbatim. No user-level identity beyond the socket owner was designed (FEAT-434 later added peercred).

## Citations

- path: `sdd/specs/agent-cli-daemon.spec.md`
  lines: 40-52, 83-97, 121-131
  symbol: `Goals / Overview / Integration Points`
  excerpt: |
    - Expose the daemon over a **Unix domain socket speaking JSON-RPC 2.0** (NDJSON framing), authenticated by filesystem permissions.
      - `parrot mcp-serve <name>` — an MCP stdio server proxying tools (...) to the daemon, so external LLMs (Claude Code, etc.) can converse with the agent.
    | `ServerAgentProxy` / `_ServerBotProxy` (`parrot.cli.loaders`) | pattern reference | `DaemonAgentProxy` mirrors its duck-typed interface |

## Notes

-
