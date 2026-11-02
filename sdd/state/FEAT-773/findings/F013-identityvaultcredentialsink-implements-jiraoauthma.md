---
id: F013
query_id: Q032
type: read
intent: "R1: read IdentityVaultCredentialSink — how OAuth tokens are sealed into navigator-auth Identity Vault."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-013]
---

# F013 — IdentityVaultCredentialSink implements JiraOAuthManager.CredentialSink over navigator-auth IdentityStore (save_linked_identity at link, update_tokens on refresh); resolves nav_user_id from state or by provider account

## Summary

`parrot/services/identity_credential_sink.py` (171 lines, server, FEAT-735). `__init__(db_pool, provider="jira")`; `_store()` → `navigator_auth.identity.store.IdentityStore(db_pool)`; `_as_token_response(JiraTokenSet)` → `navigator_auth.identity.types.TokenResponse`. `persist_minted` resolves `nav_user_id` from `state_payload["extra"]["nav_user_id"]`, else `store.find_user_by_provider_account(provider, account_id)`; if none → warn & skip; else `save_linked_identity(user_id, provider, token, ...)`. `persist` (refresh) uses `update_tokens`, never `save_linked_identity`. Docstring: one grant used to live in three unsynchronised places (Redis, Session Vault, Identity Vault); FEAT-735 made Identity Vault the owner.

## Citations

- path: `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py`
  lines: 1-15
  symbol: `module docstring`
  excerpt: |
    One Atlassian 3LO grant used to live in three unsynchronised places: Redis (the live tool read path), the Session Vault (auth.user_vault_secrets) and the Identity Vault (auth.user_identities). FEAT-735 named the **Identity Vault** the durable owner
- path: `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py`
  lines: 24-43
  symbol: `IdentityVaultCredentialSink`
  excerpt: |
    class IdentityVaultCredentialSink:
        def __init__(self, db_pool: Any, provider: str = "jira")
        def _store(self): from navigator_auth.identity.store import IdentityStore; return IdentityStore(self._db_pool)
- path: `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py`
  lines: 64-121
  symbol: `IdentityVaultCredentialSink.persist_minted`
  excerpt: |
    nav_user_id = extra.get("nav_user_id")
    if not nav_user_id and account_id:
        nav_user_id = await self._store().find_user_by_provider_account(self._provider, account_id)
    if not nav_user_id: ...skip
    await self._store().save_linked_identity(user_id=nav_user_id, provider=self._provider, ...)
- path: `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py`
  lines: 123-171
  symbol: `IdentityVaultCredentialSink.persist`
  excerpt: |
    # Uses update_tokens, never save_linked_identity

## Notes

A principal-keyed durable OAuth credential store ALREADY exists for Jira (navigator-auth Identity Vault keyed by nav user_id + provider + provider account). The brainstorm's 'principal-keyed vault entry for OAuth tokens … believed NOT to exist' is wrong for Jira. Wired by `integrations/manager.py` (FC-057).
