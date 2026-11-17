---
id: F059
query_id: Q006
type: wiki_page
intent: "Read spec: one owner for the Jira credential (VaultTokenSync vs IdentityStore tech debt) — decides vault consolidation."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FW-006]
---

# F059 — FEAT-735 (approved, all 5 tasks done 2026-10-23): Identity Vault (`auth.user_identities`) is the DURABLE owner of the Jira grant, Redis stays the hot cache, Session-Vault `jira:*` write retired; `CredentialSink` Protocol added to `JiraOAuthManager`

## Summary

Decision trail that the proposal must inherit, not reopen: Q1 (2026-10-23) — Identity Vault owns the credential, Redis (`JiraOAuthManager`, TTL 90d) stays the live read path for `JiraToolkit` (G4: no per-call Postgres decrypt). `JiraOAuthManager` gained `credential_sink: Optional[CredentialSink]` (Protocol `persist(channel, user_id, token)`) called after `_write_token` in both `_refresh_tokens` (M1) and `handle_callback` (M1b, `persist_minted` with state payload); the concrete `IdentityVaultCredentialSink` lives in the server package and resolves the Navigator user via `extra.nav_user_id` → `IdentityStore.find_user_by_provider_account("jira", account_id)` → logged no-op. `IntegrationsService._token_status` now reads the owner for `_IDENTITY_OWNED_PROVIDERS = {"jira"}` (M2). `post_auth_jira._store_in_vault` and its `token=` upsert were removed (M3). Q3: existing `jira:*` vault keys left in place, inert. Q4/G5: Slack & Teams first links still have no owner unless the state carries `nav_user_id` (Teams fixed by TASK-4667; Slack still gap). `docs/auth/jira-credential-ownership.md` written (M4). Non-goals: `VaultTokenSync` for fireflies/workiq/entra/o365 untouched; `CredentialResolver`/broker design untouched.

## Citations

- path: `sdd/specs/services-vault-token-sync-tech-debt.spec.md`
  lines: n/a
  symbol: FEAT-735 §1 three-store table, §2 Overview, §3 M1/M1b/M2/M3/M4, §6 contract (`jira_oauth.py:386 _write_token`, `:439 handle_callback`, `:498` link-time sink site, `:547 get_valid_token`, `:642 _refresh_tokens`; `oauth2/service.py:173 _token_status`; `vault_token_sync.py:99/181/244/294/308`)
  wiki_page_id: file:sdd/specs/services-vault-token-sync-tech-debt.spec.md
- path: `packages/ai-parrot/src/parrot/auth/jira_oauth.py`
  lines: n/a
  symbol: `JiraOAuthManager.__init__(..., credential_sink=None)`, `CredentialSink` Protocol, `_refresh_tokens`, `handle_callback`, `JiraTokenSet`
- path: `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py`
  lines: n/a
  symbol: `IdentityVaultCredentialSink` (`persist_minted`, `persist`, `_as_token_response`)
  wiki_page_id: file:packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py (score=0.79)
- path: `packages/ai-parrot/src/parrot/auth/oauth2/service.py`
  lines: n/a
  symbol: `_IDENTITY_OWNED_PROVIDERS`, `IntegrationsService._identity_token_status`, `_token_status`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/oauth2/service.py
- path: `packages/ai-parrot-integrations/src/parrot/integrations/manager.py`
  lines: n/a
  symbol: two `JiraOAuthManager(` construction sites (spec §6 anchors `manager.py:338`, `:896`) where the sink is wired
- path: `docs/auth/jira-credential-ownership.md`
  lines: n/a
  symbol: ownership doc (M4)
- path: `sdd/tasks/index/services-vault-token-sync-tech-debt.json`
  lines: n/a
  symbol: TASK-4668..4672 all `done`, completed_at 2026-10-23T21:42

## Notes

Implication for the brainstorm's "principal-keyed vault": for Jira the durable copy IS already keyed by Navigator principal `(user_id, "jira", account_id)` in `auth.user_identities`; only the hot Redis cache remains channel-keyed (`jira:oauth:{channel}:{user_id}`). The "dual-read window / zero-reconnect migration" the brainstorm plans should target the Redis cache key, not the durable store. Hard rule from §7: `ai-parrot` core must NOT import `ai-parrot-server` (`parrot.services.*`) — hence Protocol-based sink injection. `[cross-lane: type=read, intent=docs/auth/jira-credential-ownership.md and jira_oauth.py sink call sites]`.
