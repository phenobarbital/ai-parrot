---
id: FC-007
query_id: Q020
type: grep
intent: "How stdio toolkit servers reach secrets"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-007 — stdio toolkit servers read no vault; env via ToolkitSection.env is the only secret channel

## Summary

Grep over toolkit_server.py, toolkit_config.py, local_server.py, toolkit_seed.py for vault/navconfig/environ/credentials finds only the navconfig stdout-purity comment (toolkit_server.py:16-17). `ToolkitSection.env` (toolkit_config.py:46-47, 57) is documented as the way to pass API keys/secrets to the server process via installer entries. No `VaultTokenSync`, no `CredentialBroker`, no per-user token path exists in the stdio server stack.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/toolkit_config.py`
  lines: 46-57
  symbol: `ToolkitSection.env`
  excerpt: |
    env: Dictionary of environment variables to pass to the toolkit server process
        (via installer entries). Useful for API keys or secrets.
    ...
    env: dict[str, str] = Field(default_factory=dict)

- path: `packages/ai-parrot/src/parrot/mcp/toolkit_server.py`
  lines: 14-22
  symbol: `module comment (navconfig import hazard)`
  excerpt: |
    # NOTE: `LLMFactory` is intentionally NOT imported at module level. Its
    # import chain (parrot.clients.factory -> ... -> navconfig) triggers
    # navconfig's eager settings-loading side effects, which include a raw print()


## Notes

Design constraint from FEAT-485 spec: stdio servers must never import ai-parrot-server/aiohttp/navconfig (see FC-031).
