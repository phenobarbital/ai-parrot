---
id: F019
query_id: [Q039, Q039-F1]
type: [grep, read]
intent: "R3: absence check — WebOAuthManager / StateStore / TokenStore / NeedsAuthorizationError designed in the NetSuite session."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 1
merged_from: [FC-020, FC-042]
---

# F019 — NeedsAuthorizationError, WebOAuthManager and StateStore do NOT exist; only `TokenStore` exists (parrot/mcp/oauth.py) with InMemory/Redis/Vault backends

## Summary

**[FC-020]** Grep over `packages/` (*.py) for `NeedsAuthorizationError|WebOAuthManager|class StateStore|class TokenStore`: the only source hit is `parrot/mcp/oauth.py:22 class TokenStore` (plus two stale `build/` copies). No `NeedsAuthorizationError`, no `WebOAuthManager`, no `StateStore` anywhere.

**[FC-042]** 280 lines. `TokenStore.get/set/delete(user_id, server_name)`; `RedisTokenStore._key` → `mcp:oauth:{server_name}:{user_id}` (no TTL); `VaultTokenStore` (:63-166) uses `store/retrieve/delete_vault_credential` with `_vault_name(user_id, server_name)`; `NetSuiteM2MAuth` (:168-280) builds an RS256 assertion, `ensure_token(user_id="m2m")`, exposes `token_supplier` property (`str | None`). No PKCE/authorization-code code in this file (moved to oauth2_state/transport).

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 22-26
  symbol: `TokenStore`
  excerpt: |
    class TokenStore:
        # Abstract token store interface.
- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 42-61
  symbol: `RedisTokenStore`
  excerpt: |
    def _key(user_id, server_name): return f"mcp:oauth:{server_name}:{user_id}"
- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 63-166
  symbol: `VaultTokenStore`
  excerpt: |
    class VaultTokenStore(TokenStore):  # backed by parrot.security.vault_utils
- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 168-280
  symbol: `NetSuiteM2MAuth`
  excerpt: |
    class NetSuiteM2MAuth: ensure_token(user_id=m2m); @property token_supplier -> str | None

## Notes

**[FC-020]** Brainstorm §10 'WebOAuthManager / StateStore / TokenStore / NeedsAuthorizationError — assumed never implemented' → 3 of 4 absent; `TokenStore` present (FC-042). `OAuthManager` for MCP was removed in TASK-1665 (FEAT-262).

**[FC-042]** MCP tokens are keyed `(user_id, server_name)` — a fourth token store shape. `WebOAuthManager`/`StateStore`/`NeedsAuthorizationError` absent (FC-020).
