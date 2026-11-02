---
id: FW-006
query_id: Q004
type: wiki_query
intent: "Orient: MCP client-side OAuth2 in core (oauth.py, oauth2_storage, oauth2_state) — is there a loopback redirect / local token store precedent for a CLI?"
executed_at: 2026-10-30T15:22:30Z
duration_ms: 2600
parent_id: null
depth: 2
---

# FW-006 — MCP client-side OAuth (FEAT-262): per-user token stores exist (memory / Redis / Vault, keyed `user_id` + `server_name`), but the flow is server-hosted (redirect route), no loopback listener

## Summary

`parrot/mcp/oauth.py` defines a `TokenStore` interface (`get/set/delete(user_id, server_name)`) with `InMemoryTokenStore`, `RedisTokenStore` (key `mcp:oauth:{server_name}:{user_id}`, L49) and `VaultTokenStore` (vault name `mcp_oauth_{server_name}_{user_id}`, L95, AES-GCM via `parrot.security.vault_utils`), plus `NetSuiteM2MAuth` (client-credentials JWT, `ensure_token(user_id)`, `token_supplier`). `parrot/mcp/oauth2_storage.py:VaultMCPTokenStorage(user_id, server_name, vault_store)` adapts that store to the MCP SDK `TokenStorage` protocol (tokens + RFC 7591 client-info). `parrot/mcp/oauth2_config.py:MCPOAuth2Config` (L27-95) carries `client_id` (None ⇒ dynamic registration by the SDK's `OAuthContext`), `auth_url`, `token_url`, `scopes`, `grant_type`, **`redirect_path`** (a server callback route) and `extra_token_params`; `HttpMCPSession._setup_oauth2` (ai-parrot-server `mcp/transports/http.py`) wires it. The wiki outline shows no `webbrowser`, `localhost` or loopback-listener symbol: the authorize leg is driven through the aiohttp server's callback route, not by a CLI process. So the precedent for S-4 is the **storage shape** (per user per remote), not an out-of-process connect flow.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 22-26
  symbol: `TokenStore`
  excerpt: |
    class TokenStore:
        async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]: ...
        async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None: ...
        async def delete(self, user_id: str, server_name: str) -> None: ...

- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 44-49
  symbol: `RedisTokenStore._key`
  excerpt: |
    return f"mcp:oauth:{server_name}:{user_id}"

- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  lines: 81-95
  symbol: `VaultTokenStore._vault_name`
  excerpt: |
    return f"mcp_oauth_{server_name}_{user_id}"

- path: `packages/ai-parrot/src/parrot/mcp/oauth.py`
  symbol: `NetSuiteM2MAuth`
  excerpt: |
    class NetSuiteM2MAuth: OAuth2 Client Credentials (M2M) for NetSuite using certificate-based JWT assertion.
        def ensure_token(self, user_id) / def token_supplier(self)

- path: `packages/ai-parrot/src/parrot/mcp/oauth2_storage.py`
  symbol: `VaultMCPTokenStorage`
  excerpt: |
    class VaultMCPTokenStorage(TokenStorage):   # mcp.client.auth.oauth2.TokenStorage
        def __init__(self, user_id: str, server_name: str, vault_store: Optional[VaultTokenStore] = None)
        get_tokens / set_tokens / get_client_info / set_client_info  — degrade to None/no-op when Vault unavailable

- path: `packages/ai-parrot/src/parrot/mcp/oauth2_config.py`
  lines: 27-95
  symbol: `MCPOAuth2Config`
  excerpt: |
    client_id: Optional[str]  # None = RFC 7591 dynamic registration
    client_secret / auth_url / token_url / scopes / grant_type / redirect_path / extra_token_params

- path: `packages/ai-parrot-server/src/parrot/mcp/transports/http.py`
  symbol: `HttpMCPSession._setup_oauth2`
  excerpt: |
    Set up MCP SDK OAuth2 provider when config.oauth2 is configured.

## Notes

Wiki: `tests/mcp/test_oauth2_e2e.py` (1.00; `TestVaultMCPTokenStorageRoundTrip`), `TASK-1663` transport OAuth2 integration (0.62), `sdd/specs/mcp-server-oauth2-support.spec.md` (0.21), `sym:MCPOAuth2Config` (0.05), `sym:HttpMCPSession._setup_oauth2` (0.02). FEAT-773's own audit finding FC-043 (add-time `user_id` binding) was surfaced too. These `mcp:oauth:*` / `mcp_oauth_*` keys are a THIRD key family alongside `oauth2:{p}:{channel}:{u}` and `jira:oauth:*` that S-1's principal-keying does not touch — worth a line in S-4's scope decision.
[cross-lane: type=grep, intent=confirm no loopback/webbrowser/localhost in parrot/mcp/*.py (plan Q017)]
[cross-lane: type=git_log, intent=mcp/oauth.py oauth2_storage.py oauth2_config.py last change dates (plan Q051)]
