---
id: FC-020
query_id: Q039
type: grep
intent: "R3: absence check — WebOAuthManager / StateStore / TokenStore / NeedsAuthorizationError designed in the NetSuite session."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-020 — NeedsAuthorizationError, WebOAuthManager and StateStore do NOT exist; only `TokenStore` exists (parrot/mcp/oauth.py) with InMemory/Redis/Vault backends

## Summary

Grep over `packages/` (*.py) for `NeedsAuthorizationError|WebOAuthManager|class StateStore|class TokenStore`: the only source hit is `parrot/mcp/oauth.py:22 class TokenStore` (plus two stale `build/` copies). No `NeedsAuthorizationError`, no `WebOAuthManager`, no `StateStore` anywhere.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 22
  symbol: `TokenStore`
  excerpt: |
    class TokenStore:
        # Abstract token store interface.

## Notes

Brainstorm §10 'WebOAuthManager / StateStore / TokenStore / NeedsAuthorizationError — assumed never implemented' → 3 of 4 absent; `TokenStore` present (FC-042). `OAuthManager` for MCP was removed in TASK-1665 (FEAT-262).
