---
id: FC-031
query_id: Q050
type: grep
intent: "R2: post-auth Jira handler that writes the credential twice (post_auth_jira / _store_in_vault)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-031 — The double-write is resolved: JiraPostAuthProvider no longer stores tokens (vault_sync retained for disconnect only); IdentityVaultCredentialSink is the sole durable writer, wired by integrations/manager.py

## Summary

Grep for `post_auth_jira|_store_in_vault|save_linked_identity|JiraPostAuthProvider|IdentityVaultCredentialSink(`: `_store_in_vault` has 0 hits (removed). `save_linked_identity` is called only in `identity_credential_sink.py:105` and `identity_mapping.py:239`. `JiraPostAuthProvider` is instantiated in `telegram/wrapper.py:603-617` with `IdentityMappingService(db_pool)` + `VaultTokenSync(db_pool, redis_client)`. `IdentityVaultCredentialSink(db_pool=db_pool)` is built in `integrations/manager.py:101`. `core/auth/post_auth.py` defines the `PostAuthProvider` protocol/registry.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`
  lines: 603-617
  symbol: `TelegramAgentWrapper (post_auth wiring)`
  excerpt: |
    identity_service = IdentityMappingService(db_pool)
    vault_sync = VaultTokenSync(db_pool, redis_client)
    provider = JiraPostAuthProvider(oauth_manager=jira_oauth, identity_service=identity_service, vault_sync=vault_sync)
    self._post_auth_registry.register(provider)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/manager.py`
  lines: 101
  symbol: `_build_credential_sink`
  excerpt: |
    return IdentityVaultCredentialSink(db_pool=db_pool)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/post_auth.py`
  lines: 15-16,101
  symbol: `PostAuthProvider registry`
  excerpt: |
    Concrete providers (e.g., JiraPostAuthProvider) live in their own modules
    registry.register(JiraPostAuthProvider(oauth_manager))

## Notes

Ledger issues e2221d566081 / 50a31674e4f2 / 2e85cce93cab appear resolved by FEAT-735 in code (see FC-032 doc).
