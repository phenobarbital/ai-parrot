---
id: FC-002
query_id: Q015
type: grep
intent: "Credential seam usages in CLI / MCP / agentd"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-002 — No broker or _cred_* seam in cli, mcp, agentd or server mcp

## Summary

Grep for `_cred_user_id|_cred_channel|set_broker(` over parrot/mcp, parrot/cli, integrations/agentd and ai-parrot-server/mcp returns a single docstring hit (identity.py:11). None of the CLI-side surfaces construct a `CredentialBroker` or inject the credential kwargs; the seam is reached only through `AbstractBot.configure()` → `ToolManager` when a bot runs in-process (REPL standalone, agentd's agent).

## Citations

- path: `packages/ai-parrot/src/parrot/cli/identity.py`
  lines: 8-12
  symbol: `module docstring`
  excerpt: |
    ``AbstractBot.ask(permission_context=...)`` threads through to the
    ``ToolManager`` → ``AbstractTool`` credential seam (see
    ``tools/manager.py`` around the ``_cred_channel``/``_cred_user_id``


## Notes

Absence claim: no `set_broker(` call in parrot/mcp/*, parrot/cli/*, integrations/agentd/*, ai-parrot-server/src/parrot/mcp/*. [cross-lane: type=wiki_related, intent=confirm ToolManager.set_broker callers are only AbstractBot.configure]
