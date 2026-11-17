---
id: F030
query_id: [Q050, Q041-F1]
type: [grep, read]
intent: "R2: post-auth Jira handler that writes the credential twice (post_auth_jira / _store_in_vault)."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 1
merged_from: [FC-031, FC-057]
---

# F030 — The double-write is resolved: JiraPostAuthProvider no longer stores tokens (vault_sync retained for disconnect only); IdentityVaultCredentialSink is the sole durable writer, wired by integrations/manager.py

## Summary

**[FC-031]** Grep for `post_auth_jira|_store_in_vault|save_linked_identity|JiraPostAuthProvider|IdentityVaultCredentialSink(`: `_store_in_vault` has 0 hits (removed). `save_linked_identity` is called only in `identity_credential_sink.py:105` and `identity_mapping.py:239`. `JiraPostAuthProvider` is instantiated in `telegram/wrapper.py:603-617` with `IdentityMappingService(db_pool)` + `VaultTokenSync(db_pool, redis_client)`. `IdentityVaultCredentialSink(db_pool=db_pool)` is built in `integrations/manager.py:101`. `core/auth/post_auth.py` defines the `PostAuthProvider` protocol/registry.

**[FC-057]** `integrations/manager.py:85-107` `_build_credential_sink(app)` returns `IdentityVaultCredentialSink(db_pool=app['authdb'])` or None with warning 'Jira refreshes will update Redis only'. `handlers/user.py:115-135` `_on_startup` creates `aioredis.ConnectionPool.from_url(self.redis_url, max_connections=5000)`, registers default channels; `register_channel` defined at :151 and :489 (duplicate). `parrot/auth/templates/`: `web_oauth_error.html` (770B), `web_oauth_success.html` (843B).

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
  lines: 85-107
  symbol: `_build_credential_sink`
  excerpt: |
    return IdentityVaultCredentialSink(db_pool=db_pool)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/post_auth.py`
  lines: 15-16,101
  symbol: `PostAuthProvider registry`
  excerpt: |
    Concrete providers (e.g., JiraPostAuthProvider) live in their own modules
    registry.register(JiraPostAuthProvider(oauth_manager))
- path: `packages/ai-parrot-server/src/parrot/handlers/user.py`
  lines: 115-135
  symbol: `UserSocketManager._on_startup`
  excerpt: |
    self.pool = aioredis.ConnectionPool.from_url(self.redis_url, encoding="utf8", decode_responses=True, max_connections=5000)
    for channel in self.default_channels: self.register_channel(channel)
- path: `packages/ai-parrot/src/parrot/auth/templates/web_oauth_success.html`
  lines: —
  symbol: `template`
  excerpt: |
    postMessage success page used by oauth2_routes / routes web branch

- path: `packages/ai-parrot-integrations/src/parrot/integrations/manager.py`
  lines: 81-107
  symbol: `_build_jira_credential_sink`
  excerpt: |
    def _build_jira_credential_sink(app: Any) -> Any:
        ... return IdentityVaultCredentialSink(db_pool=db_pool)

## Notes

**[FC-031]** Ledger issues e2221d566081 / 50a31674e4f2 / 2e85cce93cab appear resolved by FEAT-735 in code (see FC-032 doc).

**[FC-057]** The Jira callback success page for web already `postMessage`s to the opener (brainstorm §5 item 7).

[citation-check: stale] packages/ai-parrot-integrations/src/parrot/integrations/manager.py:81 — symbol is `_build_jira_credential_sink` (lines 81-107), not `_build_credential_sink`; call sites at :372 and :931 pass `credential_sink=_build_jira_credential_sink(app)`.
