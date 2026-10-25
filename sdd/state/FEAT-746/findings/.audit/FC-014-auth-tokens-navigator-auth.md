---
id: FC-014
query_id: [Q033, Q050]
type: read
intent: "Auth: navigator-auth integration, token types, any capability/attenuation (biscuit, macaroon); token exchange shape."
executed_at: 2026-10-25T22:47:25Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-014 — navigator-auth integration is session/OAuth2/PBAC based (token exchange, grants, approval tokens, OAuth2 providers); zero hits for biscuit / macaroon / attenuated capability tokens

## Summary

`parrot/auth/` contains `token_exchange.py` (`TokenExchangeClient(auth_url, timeout, prefer_id_token).exchange(...) -> ExchangeResult` with reasons `ok|user_not_found|backend_not_loaded|invalid_token|expired|transport_error` — exchanges an external provider token for a Navigator session), `grants.py`, `approval_token.py`, `confirmation.py`, `credentials.py`, `broker/{core,byok,factory}.py` (CredentialBroker), `identity.py`, `session_identity.py`, `system_account.py`, `manifest.py`, `rls_registry.py`, the OAuth2 stack `oauth2/{service,registry,models,persistence,mcp_provider,jira_provider,o365_*,workiq_provider}.py` and `oauth2_routes.py`. A case-insensitive grep for `biscuit|macaroon` over every package returned nothing, confirming the VERIFY claim: attenuated capability tokens do not exist. MCP servers authenticate via API key / bearer / OAuth internal or external (`RemoteMCPServerBase._authenticate_*`, FC-003); the mTLS-identifies-the-agent model of the brainstorm has no counterpart found.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/token_exchange.py`
  lines: 1-21
  symbol: module docstring + reason constants
  excerpt: |
    """Exchange an external provider token for a Navigator session."""
    REASON_OK = "ok"
    REASON_USER_NOT_FOUND = "user_not_found"
    REASON_INVALID_TOKEN = "invalid_token"
    REASON_EXPIRED = "expired"
- path: `packages/ai-parrot/src/parrot/auth/token_exchange.py`
  lines: 25-63
  symbol: `ExchangeResult`, `TokenExchangeClient`, `exchange`
  excerpt: |
    class TokenExchangeClient:
        def __init__(self, auth_url: str, timeout: int = 15, prefer_id_token: bool = True) -> None:
        async def exchange(
- path: `packages/ai-parrot/src/parrot/auth/approval_token.py`
  lines: 1
  symbol: (approval token module — not read)
- path: `packages/ai-parrot/src/parrot/auth/grants.py`
  lines: 1
  symbol: (grants module — not read)
- path: `packages/ai-parrot/src/parrot/auth/broker/core.py`
  lines: 1
  symbol: `CredentialBroker` (imported by A2AServer as `from parrot.auth.broker import CredentialBroker`)
- path: `packages/ai-parrot/src/parrot/auth/oauth2/service.py`
  lines: 1
  symbol: (OAuth2 service — matched navigator-auth grep)
- path: `packages/ai-parrot/src/parrot/auth/oauth2/mcp_provider.py`
  lines: 52
  symbol: `pbac_action_namespace`
- path: `packages/ai-parrot-server/src/parrot/a2a/server.py`
  lines: 217-219
  symbol: CredentialBroker wiring
  excerpt: |
    from parrot.auth.broker import CredentialBroker as _CB
    _b = _CB(audit_ledger=audit_ledger)

## Notes

The `grants.py` + `GrantGuard` (ToolManager.set_grant_guard, FC-004) mechanism may be the closest in-repo notion of a scoped delegation; not read. [cross-lane: type=wiki_query, intent="grant guard scoped grants delegation" to characterise grants.py]
