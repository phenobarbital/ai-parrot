---
id: F057
query_id: Q004
type: wiki_query
intent: "Orient: vault semantics — VaultTokenSync, vault_utils, ai_user_credentials, BYOK session scope."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FW-004]
---

# F057 — "Session vault" = navigator-session `auth.user_vault_secrets` (via `vault_utils` / `VaultTokenSync`); a separate Postgres `navigator.ai_user_credentials` store behind `VAULT_STORE` (FEAT-621) and the navigator-auth Identity Vault (`auth.user_identities`) also hold per-user secrets

## Summary

Three per-user secret stores exist, none keyed `(tenant, principal, provider, account)` as the brainstorm wants. (1) **Session Vault** — navigator-session encrypted store `auth.user_vault_secrets`, accessed by `parrot/security/vault_utils.py` (`store_vault_credential`, `retrieve_vault_credential`, `delete_vault_credential`; envelope v2 via `security/credentials_utils.py`, FEAT-099) and wrapped per provider by `ai-parrot-server/src/parrot/services/vault_token_sync.py` `VaultTokenSync` (`store_tokens(nav_user_id, provider, tokens)`, `read_tokens`, `read_tokens_result -> VaultTokenRead(status missing|unreadable|ok)`, `delete_tokens`; flat `{provider}:{field}` keys, synthesises a `telegram-persistent:` session uuid — a Telegram-flavoured scheme FEAT-266 flagged). Used today by fireflies (`fireflies:api_key`), workiq/entra (`workiq_provider.py`), o365 device-code (`o365:*`). It persists across sessions (it is the per-user vault, not TTL'd session data) and is encrypted at rest. (2) **Postgres vault store** `handlers/studio/storage/vault_store.py` — "Vault credentials in Postgres" in `navigator.ai_user_credentials` behind `VAULT_STORE` (FEAT-621 TASK-3953), plus BYOK per-user LLM keys (`handlers/studio/byok.py`, TASK-2516, `BYOK_STORE=documentdb|postgres`). (3) **Identity Vault** `auth.user_identities` — navigator-auth `IdentityStore` seals tokens bound to `(user_id, auth_provider, provider_user_id, column)`; FEAT-735 made it the durable owner of the Jira grant with Redis as hot cache. Also the generic `AbstractOAuth2Manager` writes vault key `oauth2_{provider}_{channel}_{user_id}` + Redis `oauth2:{provider}:{channel}:{user_id}`. FEAT-063 `user-based-credentials` (asyncdb DB credentials) is a fourth, DocumentDB-backed `user_credentials` collection — DB creds only, not OAuth.

## Citations

- path: `packages/ai-parrot/src/parrot/security/vault_utils.py`
  lines: n/a
  symbol: `store_vault_credential`, `retrieve_vault_credential`, `delete_vault_credential`
  wiki_page_id: file:packages/ai-parrot/src/parrot/security/vault_utils.py (score=0.65)
- path: `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py`
  lines: n/a
  symbol: `VaultTokenSync` (`store_tokens`, `read_tokens`, `read_tokens_result`, `delete_tokens`), `VaultTokenRead`
  wiki_page_id: file:packages/ai-parrot-server/src/parrot/services/vault_token_sync.py (score=0.20)
- path: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_store.py`
  lines: n/a
  symbol: Postgres vault credentials store (`navigator.ai_user_credentials`, `VAULT_STORE`)
  wiki_page_id: file:packages/ai-parrot-server/src/parrot/handlers/studio/storage/vault_store.py (score=1.00)
- path: `packages/ai-parrot-server/src/parrot/handlers/studio/byok.py`
  lines: n/a
  symbol: BYOK per-user LLM API keys + `CredentialBroker` resolver (TASK-2516)
  wiki_page_id: file:packages/ai-parrot-server/src/parrot/handlers/studio/byok.py (score=0.77)
- path: `packages/ai-parrot/src/parrot/security/credentials_utils.py`
  lines: n/a
  symbol: credential encryption helpers — envelope v2 (FEAT-099)
  wiki_page_id: file:packages/ai-parrot/src/parrot/security/credentials_utils.py (score=0.52)
- path: `packages/ai-parrot/src/parrot/vault_targets.py`
  lines: n/a
  symbol: Vault protected targets for DocumentDB collections (FEAT-099)
  wiki_page_id: file:packages/ai-parrot/src/parrot/vault_targets.py (score=0.46)
- path: `sdd/tasks/completed/TASK-3953-p2-vault-credentials-postgres.md`
  lines: n/a
  symbol: Phase 2 vault credentials in `navigator.ai_user_credentials` behind `VAULT_STORE`
  wiki_page_id: file:sdd/tasks/completed/TASK-3953-p2-vault-credentials-postgres.md (score=0.94)
- path: `sdd/specs/user-based-credentials.spec.md`
  lines: n/a
  symbol: FEAT-063 CredentialsHandler, DocumentDB `user_credentials`, session key `_credentials:{name}`
  wiki_page_id: file:sdd/specs/user-based-credentials.spec.md (score=0.23)

## Notes

Spike S1 answer in outline: the "session vault" is persistent per *user* (navigator-session's user vault), encrypted, not per browser session; the ephemeral BYO-API-key scope the brainstorm describes is closer to FEAT-063's `_credentials:{name}` session keys + DocumentDB. The `CredentialVault` ABC proposed in the brainstorm does not exist; the nearest abstraction is `VaultTokenSync` (server pkg) + `vault_utils` (core). `[cross-lane: type=read, intent=read vault_token_sync.py for key shape/_synth_session_uuid/_coerce_user_id and vault_utils.py for encryption + storage backend]`.
