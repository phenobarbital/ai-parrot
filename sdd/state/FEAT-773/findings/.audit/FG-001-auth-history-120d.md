---
id: FG-001
query_id: Q060
type: git_log
intent: "History: recent commits on parrot/auth (broker, oauth2, routes) — what landed in the last 120 days."
executed_at: 2026-10-30T12:05:12Z
duration_ms: 900
parent_id: null
depth: 0
---

# FG-001 — parrot/auth: 37 commits in 120 days; Oct 2026 wave is Jira-credential ownership + Teams user-auth lane

## Summary

37 commits (2026-07-03 → 2026-10-23) touched `packages/ai-parrot/src/parrot/auth/`; authors Jesus Lara / Jesus (plus `revbot` for agentstudio). Dominant themes, newest first: (1) **services-vault-token-sync-tech-debt** (2026-10-23, TASK-4668/4669/4670) — `JiraOAuthManager` gained an optional structural `CredentialSink` Protocol so a refresh and a link both propagate the Jira grant to navigator-auth's Identity Vault (`auth.user_identities`); the integrations badge now reads that owner for Jira. (2) **msteams-user-auth-lane** (2026-10-23, TASK-4660/4661/4663) — new `parrot/auth/token_exchange.py` (165 lines) for Teams token exchange with a fail-closed gate. (3) **jiratoolkit-upgrades** (2026-10-16/17, TASK-4418) — 3LO helpers (`exchange_code`, `refresh_access_token`, `fetch_accessible_resources`, `fetch_myself`) extracted in `jira_oauth.py` (+144/-41) and later hardened (error-body truncation, CSRF state check for CLI). (4) **vault-crypto-hardening** (2026-09-16, TASK-079/082) — envelope v2 context-bound seal/open in `security/credentials_utils.py`, process-wide KeyRing in `vault_utils.py`, and `oauth2/service.py` + `oauth2/models.py` gained an `IntegrationDescriptor.status` (connected | disconnected | needs_reconnect) probed from `VaultTokenSync`. (5) **BYOK** (2026-08-27, TASK-2516) — `parrot/auth/broker.py` grew a CredentialBroker resolver for per-user LLM keys (+148 lines). No commit in this window creates a `connections` module, a generic `ConnectionManager`, or touches `oauth2_routes.py` directly. Note: the broker lived at `parrot/auth/broker.py` in Aug–Sep 2026; the wiki now lists `parrot/auth/broker/core.py` — a package split happened (cross-lane check).

## Citations

- sha: `79c856423` · 2026-10-23 · Jesus Lara · feat(services-vault-token-sync-tech-debt): TASK-4670 — the integrations badge reads the owner
  files: `packages/ai-parrot/src/parrot/auth/oauth2/service.py` (+86/-3) — new `_identity_token_status`; Jira probes Identity Vault (`get_by_provider` + `decrypt_credential`); other providers keep the Session Vault path; fail-open preserved (outage reads "connected").
- sha: `6aa0e639d` · 2026-10-23 · Jesus Lara · feat(services-vault-token-sync-tech-debt): TASK-4669 — write the owner at link time too
  files: `packages/ai-parrot/src/parrot/auth/jira_oauth.py` (+28), `packages/ai-parrot-server/src/parrot/services/identity_credential_sink.py` (+61) — `handle_callback` notifies the sink; `persist_minted` resolves the Navigator user from OAuth state `extra.nav_user_id` (only the Telegram flow puts a Navigator id in the state; first-ever Slack/Teams link has no owner → logged no-op).
- sha: `e8f043d0f` · 2026-10-23 · Jesus Lara · feat(services-vault-token-sync-tech-debt): TASK-4668 — propagate a refreshed Jira grant to the Identity Vault
  files: `parrot/auth/jira_oauth.py` (+35), `parrot/services/identity_credential_sink.py` (+112, new), `parrot/integrations/manager.py` (+30) — `JiraOAuthManager(credential_sink: CredentialSink | None)`; order Redis first, sink second; sink failure logged, never changes return.
- sha: `5be2498fc` / `0ee1f6a37` · 2026-10-23 · Jesus · feat/fix(msteams-user-auth-lane): TASK-4660/4661/4663
  files: `packages/ai-parrot/src/parrot/auth/token_exchange.py` (+165 new, +11), `integrations/msteams/auth.py`, `integrations/msteams/wrapper.py` — fail-closed gate, exchange hardening, Token Service user id.
- sha: `4b2d17b0a` · 2026-10-16 · Jesus · feat(jiratoolkit-upgrades): TASK-4418 — extract 3LO OAuth helpers
  files: `parrot/auth/jira_oauth.py` (+144/-41).
- sha: `6039b0507` · 2026-10-17 · Jesus · fix(jiratoolkit-upgrades): require full redirect URL for CLI auth, truncate OAuth error bodies, handle corrupt token store
  files: `parrot/auth/jira_oauth.py`, `parrot_tools/jira_cli.py`, `parrot_tools/jira_local_auth.py`.
- sha: `ea23a57a9` · 2026-09-16 · Jesus Lara · feat(vault-crypto-hardening): TASK-082 — integrations needs_reconnect status and VaultTokenSync F4 regression
  files: `parrot/services/vault_token_sync.py` (+97), `parrot/auth/oauth2/models.py` (+25), `parrot/auth/oauth2/service.py` (+71) — `VaultTokenSync.read_tokens_result()` → typed `VaultTokenRead` (ok/missing/unreadable/unavailable); SessionVault cached per instance; `IntegrationDescriptor.status`.
- sha: `4e5674796` · 2026-09-16 · Jesus Lara · feat(vault-crypto-hardening): TASK-079 — context-bound credential helpers and DocumentDB targets
  files: `parrot/auth/broker.py` (+14), `parrot/security/credentials_utils.py` (+167), `parrot/security/vault_utils.py` (+83) — envelope v2 seal/open bound to (user_id, name, credential) / (user_id, provider, api_key); KeyRing; `UserCredentialsTarget`/`UserLlmKeysTarget` over DocumentDB.
- sha: `77ef3b6eb` · 2026-08-27 · Jesus Lara · feat(agentstudio-management): TASK-2516 — BYOK per-user LLM API keys + CredentialBroker resolver
  files: `parrot/auth/broker.py` (+148), `parrot/handlers/studio/byok.py` (+260 new).
- sha: `322b3d067` / `08a5718fd` · 2026-08-24 · Jesus Lara · saas-auth-hardening TASK-2321/2320 — `parrot/auth/eval_context.py` (new), `parrot/auth/pbac.py` (PARROT_SAAS_MODE, setup_pbac fail-closed).
- sha: `6c7e82a85` · 2026-07-20 · Jesus · feat(parrot-eventbus-migration): TASK-1831 — rewire imports (auth: `permission.py` 1 line).

## Notes

- Everything in the Oct-23 wave is about *who owns the Jira credential* — the exact question the brainstorm's spike S1 asks. The answer in git: the Identity Vault row in `auth.user_identities` (navigator-auth), fed by a `CredentialSink`; the Session Vault (`VaultTokenSync`) copy of Jira tokens was being retired (see FG-002/FG-003).
- Nothing in 120 days created `parrot.connections`, `ConnectionManager`, `OAuthProviderRegistry` or `connection.*` events.
- [cross-lane: type=read, intent=confirm the broker package split — `parrot/auth/broker.py` (Aug–Sep 2026) vs `parrot/auth/broker/core.py` (wiki); cite the current path]
- [cross-lane: type=read, intent=read `parrot/auth/token_exchange.py` (TASK-4660) — a second token-exchange helper besides `jira_oauth.py`; candidate for the generic manager]
- [cross-lane: type=read, intent=read `parrot/auth/oauth2/service.py` + `oauth2/models.py` — `IntegrationsService`, `IntegrationDescriptor.status`, `_token_status`/`_identity_token_status`: this is already a per-user "connections list" API]
