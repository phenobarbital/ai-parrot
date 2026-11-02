---
id: F004
query_id: [Q017, Q051]
type: [git_log, grep]
intent: "Loopback redirect / token-store precedent in parrot.mcp"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-004, FG-004]
---

# F004 — No loopback OAuth in parrot.mcp; token stores exist (memory/redis/vault)

## Summary

**[FC-004]** parrot.mcp has no loopback redirect, no `webbrowser`, no 127.0.0.1 callback listener for a CLI OAuth flow. What exists: `TokenStore` + `InMemoryTokenStore`/`RedisTokenStore`/`VaultTokenStore` (oauth.py) keyed `(user_id, server_name)`, `VaultMCPTokenStorage` adapting the MCP SDK `TokenStorage` protocol (oauth2_storage.py), and `MCPOAuth2Config.redirect_base_url` whose default is `NAVIGATOR_BASE_URL` → `http://127.0.0.1:8000` with path `/api/auth/oauth2/mcp/callback` — i.e. the aiohttp server's callback, not a CLI loopback.

**[FG-004]** 10 commits (2026-03-23 → 2026-06-26), all by Jesus. `oauth.py` originated with the monorepo migration
(TASK-398, 2026-03-23), gained NetSuite support (TASK-922, 2026-04-29), was split/relocated for
ai-parrot-server (TASK-1366/1368, 2026-05-29). `oauth2_config.py` and `oauth2_storage.py` were
created by the `mcp-server-oauth2-support` feature on 2026-06-26 (TASK-1659 `MCPOAuth2Config`,
TASK-1660 **`VaultMCPTokenStorage` adapter** +171 lines with 235 lines of tests, TASK-1665 OAuth in
`oauth.py`, then review fixes `4748de100`). **Nothing has touched these three files in the four
months since 2026-06-26** — the MCP client-side OAuth path is stable/frozen, consistent with S-1's
note that `mcp/client.py` is frozen since 2026-06-29.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 22-26, 42-49, 63-70
  symbol: `TokenStore / RedisTokenStore._key / VaultTokenStore`
  excerpt: |
    class TokenStore:
        async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]: ...
    class RedisTokenStore(TokenStore):
        def _key(user_id: str, server_name: str) -> str:
            return f"mcp:oauth:{server_name}:{user_id}"
    class VaultTokenStore(TokenStore):  # mcp_oauth_{server_name}_{user_id}
- path: `packages/ai-parrot/src/parrot/mcp/oauth2_config.py`
  lines: 79-91
  symbol: `MCPOAuth2Config.redirect_path / redirect_base_url`
  excerpt: |
    redirect_path: str = Field(default="/api/auth/oauth2/mcp/callback", ...)
    redirect_base_url: str = Field(default="", description=(
        "... When empty, the NAVIGATOR_BASE_URL environment variable is used, falling back to 'http://127.0.0.1:8000'. "))
- path: `packages/ai-parrot/src/parrot/mcp/oauth2_storage.py`
  lines: 1-171
  symbol: `VaultMCPTokenStorage`
  excerpt: |
    class VaultMCPTokenStorage(TokenStorage):
        def __init__(self, user_id: str, server_name: str, vault_store: Optional[VaultTokenStore] = None)
- path: `packages/ai-parrot/src/parrot/mcp/oauth2_config.py`
  lines: 1-1
  symbol: `MCPOAuth2Config`
  excerpt: |
    44497f159 2026-06-26 feat(mcp-server-oauth2-support): TASK-1659 — MCPOAuth2Config
- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 1-1
  symbol: `(client-side OAuth)`
  excerpt: |
    473625b39 2026-06-26 TASK-1665 — OAuth… (oauth.py)
    461d7a0a2 2026-05-29 TASK-1368 — Split mcp/oauth… (ai-parrot-server)
    2e83e51ea 2026-05-29 TASK-1366 — Relocate vault… (oauth.py)
    fa055259b 2026-05-04 new test agents (oauth.py)
    0e03a4e67 / d9db07f77 2026-04-29 TASK-922 netsuite-mcp-integration (oauth.py)
    495361104 2026-03-23 TASK-398 monorepo-migration workspace (oauth.py)

## Notes

**[FC-004]** Other 127.0.0.1 hits (registry.py:207, integration.py:1070-1162) are Chrome DevTools URLs, unrelated.

**[FG-004]** - Test file for the storage adapter lives at the repo-root tree `tests/mcp/test_oauth2_storage.py`, not under `packages/ai-parrot/tests/`.
- The feature name `mcp-server-oauth2-support` suggests these files serve parrot-as-MCP-*client* talking to OAuth-protected remote MCP servers (NetSuite); whether a loopback redirect exists is for the codebase lane.
- [cross-lane: type=read, intent=Read oauth2_storage.py VaultMCPTokenStorage to see its key layout (user-keyed? channel-keyed?) — candidate CredentialStore precedent.]
