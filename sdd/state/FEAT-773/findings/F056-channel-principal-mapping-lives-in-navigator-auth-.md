---
id: F056
query_id: Q003
type: wiki_query
intent: "Orient: identity mapping Telegram/Teams/web → navigator-auth principal (IdentityStore, user_identities)."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FW-003]
---

# F056 — Channel→principal mapping lives in navigator-auth `auth.user_identities`: `IdentityMappingService` (raw SQL, server pkg) for channel rows + `IdentityStore` (navigator-auth) for the Jira credential; `nav_user_id` only travels in the Telegram OAuth state

## Summary

`IdentityMappingService` (`ai-parrot-server/src/parrot/services/identity_mapping.py`, FEAT-108 TASK-760, fixed by FEAT-729 TASK-4664) upserts `auth.user_identities` rows keyed `(user_id bigint, auth_provider, provider_user_id)` for `telegram` (telegram_id), `slack` (slack_user_id), `msteams` (aad_object_id) and `jira` (account_id) — the Jira row goes through navigator-auth's `IdentityStore.save_linked_identity` with a real `TokenResponse`; the three channel rows are metadata-only SQL because `IdentityStore` has no token-less write path. Readers: TASK-4664 noted `get_identity/get_all_identities/delete_identity` had zero callers; FEAT-735 added the first (`IntegrationsService._identity_token_status`). Key constraint recorded as wiki memory `mem-30df362979b0`: `user_id` is a bigint FK to `auth.users`, so each channel callback must carry the Navigator id under its own `nav_user_id` state key — only the Telegram combined login (`post_auth_jira.build_auth_url`) and, since TASK-4667, the Teams `/connect_jira` command do; Slack's first link has no owner (TASK-4666 skips the write). The Telegram login itself resolves the Navigator user via `TelegramUserSession.nav_user_id` populated by `NavigatorAuthClient`/`AbstractAuthStrategy` (Basic/Azure/Google/Composite strategies in `telegram/auth.py`). This answers R1: Telegram `user_id` in `PermissionContext`/Redis keys is the raw Telegram id; the platform principal is `nav_user_id`, mapped at login and persisted as a `telegram` identity row.

## Citations

- path: `packages/ai-parrot-server/src/parrot/services/identity_mapping.py`
  lines: n/a
  symbol: `IdentityMappingService` (`upsert_identity(nav_user_id, auth_provider, provider_user_id, auth_data, display_name, email, token)`, `get_identity`, `get_all_identities`, `delete_identity`), `_UPSERT_SQL`
  wiki_page_id: file:packages/ai-parrot-server/src/parrot/services/identity_mapping.py (score=0.94)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py`
  lines: n/a
  symbol: `JiraPostAuthProvider.build_auth_url` (puts `nav_user_id` in `extra_state`), `_write_identity_records`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py (score=0.43)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py`
  lines: n/a
  symbol: `TelegramUserSession`, `NavigatorAuthClient`, `AbstractAuthStrategy`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py (score=0.83)
- path: `sdd/tasks/completed/TASK-4664-identity-writes-identitystore-and-sql-fix.md`
  lines: n/a
  symbol: four call sites table (`msteams/oauth_callback.py:248`, `slack/oauth_callback.py:232`, `telegram/post_auth_jira.py:256`, `:273`); `IdentityStore` full API (`save_linked_identity`, `update_tokens`, `get_by_provider`, `get_for_provider_account`, `find_user_by_provider_account`, `decrypt_credential` (sync), `delete`, `list_for_user`, `masked`)
  wiki_page_id: file:sdd/tasks/completed/TASK-4664-identity-writes-identitystore-and-sql-fix.md (score=0.77)
- path: `sdd/tasks/completed/TASK-760-identity-mapping-service.md`
  lines: n/a
  symbol: TASK-760 Identity Mapping Service (FEAT-108)
  wiki_page_id: file:sdd/tasks/completed/TASK-760-identity-mapping-service.md (score=0.77)
- path: `sdd/tasks/completed/TASK-4666-slack-oauth-nav-user-id.md`
  lines: n/a
  symbol: Slack callback skips identity write when no Navigator id in state
  wiki_page_id: file:sdd/tasks/completed/TASK-4666-slack-oauth-nav-user-id.md (score=0.20)

## Notes

Wiki memory `mem-30df362979b0` ("nav_user_id state key for channel identity writes") is a durable decision: never reuse `state_payload['user_id']` (the channel id) as the Navigator id. Also `CanonicalIdentityMapper` (`parrot/auth/identity.py`, FEAT-264 M5) is a *different* principal notion — Entra OID → email → None — used by the broker/A2A/MSAgentSDK, not the Navigator bigint `user_id`. The proposal must reconcile these two principal keys. `[cross-lane: type=grep, intent=where telegram/wrapper.py sets session.nav_user_id after NavigatorAuthClient.login and whether PermissionContext.user_id is telegram_id or nav_user_id for tool calls]`.
