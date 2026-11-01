---
id: FW-009
query_id: Q009
type: wiki_page
intent: "Read task: TASK-4664 identity writes via IdentityStore — the current Jira credential write path."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-009 — TASK-4664 (FEAT-729, done-with-issues): `auth.user_identities` arbiter fixed to partial unique `(user_id, auth_provider, provider_user_id)`; Jira row sealed via `IdentityStore.save_linked_identity`; channel rows metadata-only; `user_id` is bigint

## Summary

Facts the proposal's data model must respect: `auth.user_identities` has PK `(user_id, uid)`, a partial UNIQUE `(user_id, auth_provider, provider_user_id) WHERE provider_user_id IS NOT NULL`, and a NON-unique `(user_id, auth_provider)` index — the canonical schema deliberately allows several accounts per provider per user (so the brainstorm's "v1 one account per provider; key has an account dimension" is already the table's shape). `IdentityStore` has NO metadata-only write; `TokenResponse.access_token` is mandatory, so channel identities (telegram/slack/msteams) stay on raw SQL in `IdentityMappingService` with `provider_user_id` keyword-required. `app['authdb']` is an asyncdb pool whose `execute()` swallowed errors — writes now use the raw asyncpg connection and raise. `decrypt_credential` is synchronous. Completion note: AC-4 real-DB Jira write was a strict xfail on navigator-auth 0.28.7 (needs 0.28.8). AC-6 recommendation (IdentityStore authoritative) later became FEAT-735's decision.

## Citations

- path: `sdd/tasks/completed/TASK-4664-identity-writes-identitystore-and-sql-fix.md`
  lines: n/a
  symbol: scope-correction table; `IdentityStore` write surface; `_UPSERT_SQL` blueprint; Completion Note
  wiki_page_id: file:sdd/tasks/completed/TASK-4664-identity-writes-identitystore-and-sql-fix.md (score=0.98)
- path: `packages/ai-parrot-server/src/parrot/services/identity_mapping.py`
  lines: n/a
  symbol: `_UPSERT_SQL`, `IdentityMappingService.upsert_identity(..., provider_user_id: str, token: Optional[TokenResponse])`
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py`
  lines: n/a
  symbol: `handle_msteams_jira_callback` (identity write, `auth_provider="msteams"`)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/slack/oauth_callback.py`
  lines: n/a
  symbol: `handle_slack_jira_callback` (identity write, `auth_provider="slack"`)
- path: `packages/ai-parrot/tests/unit/test_identity_mapping.py`
  lines: n/a
  symbol: real-Postgres tests, skip unless `IDENTITY_PG_DSN`
  wiki_page_id: file:packages/ai-parrot/tests/unit/test_identity_mapping.py (score=1.00)

## Notes

Ledger `issue:0115386145f2` (42P10) closed by this task; `issue:187ce3fe3b93` (Teams AAD GUID into bigint) closed by TASK-4667; `issue:a671f989e8e7` (Slack composite id) resolved by TASK-4666 (write skipped when no nav id). The remaining open item is `issue:e2221d566081` (see FW-021).
