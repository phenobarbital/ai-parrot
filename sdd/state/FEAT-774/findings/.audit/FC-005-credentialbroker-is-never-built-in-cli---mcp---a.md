---
id: FC-005
query_id: Q018
type: grep
intent: "Broker construction outside the server"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-005 — CredentialBroker is never built in cli / mcp / agentd

## Summary

`CredentialBroker`, `from_config(`, `_broker_deps`, `credential_provider` have no construction sites in parrot/cli, parrot/mcp or integrations/agentd. The only mcp references are the FEAT-264 comments on `MCPClientConfig.inject_broker_credential` (client.py:238, 278), which consume a broker-resolved token per call but do not build the broker. `cli/devloop/bootstrap.py` hits are `DevLoopGraphMemory.from_config()` (unrelated).

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/client.py`
  lines: 236-242, 278
  symbol: `MCPClientConfig.inject_broker_credential`
  excerpt: |
    # FEAT-264: When True, read the per-call CredentialBroker-resolved token from
    # ... _CREDENTIAL_VAR and inject it as the bearer


## Notes

Consequence for S-4: a stdio toolkit server has no broker; tools requiring credentials fail or read env/static config.
