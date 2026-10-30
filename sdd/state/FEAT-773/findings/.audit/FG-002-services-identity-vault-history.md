---
id: FG-002
query_id: Q061
type: git_log
intent: "History: identity + vault services churn (FEAT-729/735) — recency of the owner decision."
executed_at: 2026-10-30T12:05:12Z
duration_ms: 800
parent_id: null
depth: 0
---

# FG-002 — server/services: 22 commits; the Jira-credential owner decision landed 2026-10-23 (FEAT-729 + FEAT-735)

## Summary

22 commits (2026-07-23 → 2026-10-23) on `packages/ai-parrot-server/src/parrot/services/`. Two themes: commcenter/notify work (Emmanuel Arroyo, Aug 2026, unrelated) and the **identity + vault** wave by Jesus on 2026-10-23: FEAT-729 **msteams-user-auth-lane** (TASK-4664: identity writes via `IdentityStore` for Jira + fixed partial-index SQL for channel providers; TASK-4667: Teams carries the Navigator user id separately from the AAD object id in the Jira OAuth state, fail-closed on non-numeric nav id) and FEAT-735 **services-vault-token-sync-tech-debt** (TASK-4668/4669: new `IdentityVaultCredentialSink`). `IdentityMappingService` (`identity_mapping.py`) grew +187/-41 in TASK-4664 and now rejects a non-numeric `nav_user_id` on both write paths; a follow-up fix (`13838cfb4`) corrected a jsonb stamping bug that silently dropped `account_id/cloud_id/site_url` from Jira identity rows (fixed with `$2::text::jsonb`), validated against real Postgres on navigator-auth 0.28.8. `VaultTokenSync` last changed 2026-09-16 (TASK-082, typed reads). The owner decision is one week old at research time — fresh and still carrying open issues (2e85cce93cab, 187ce3fe3b93, a671f989e8e7 referenced in messages).

## Citations

- sha: `a11d28521` · 2026-10-23 · Jesus · feat(msteams-user-auth-lane): TASK-4664 — identity writes via IdentityStore (jira) and fixed partial-index SQL (channels)
  files: `packages/ai-parrot-server/src/parrot/services/identity_mapping.py` (+187/-41), `integrations/msteams/oauth_callback.py` (+27), `integrations/slack/oauth_callback.py` (+1), `integrations/telegram/post_auth_jira.py` (+26).
- sha: `13838cfb4` · 2026-10-23 · Jesus Lara · fix(msteams-user-auth-lane): TASK-4664 — Jira auth_data stamp wrote a jsonb array
  files: `parrot/services/identity_mapping.py` (+8/-1) — `_STAMP_METADATA_SQL` `$2::jsonb` appended a JSON string scalar; now `$2::text::jsonb`; requires navigator-auth ≥ 0.28.8 (`UserIdentity` accepts `id_token=None`).
- sha: `dffe01eda` · 2026-10-23 · Jesus · fix(msteams-user-auth-lane): TASK-4667 — carry the Navigator user id in the Teams Jira OAuth state
  files: `integrations/msteams/commands/jira_commands.py` (+72), `integrations/msteams/oauth_callback.py` (+71/-32), `integrations/msteams/wrapper.py` (+8), `parrot/services/identity_mapping.py` (+14) — AAD object id stays the Jira token key and becomes `provider_user_id`; `nav_user_id` rides in its own state key (resolved per turn via `MSTeamsAgentWrapper._effective_user_id`); callback skips the write with no nav id.
- sha: `e8f043d0f` · 2026-10-23 · Jesus Lara · TASK-4668 — `identity_credential_sink.py` (+112, new): `IdentityVaultCredentialSink` resolves the Navigator user from the Atlassian account id, re-seals with `update_tokens` (never `save_linked_identity`, which would reset `auth_data`).
- sha: `6aa0e639d` · 2026-10-23 · Jesus Lara · TASK-4669 — `identity_credential_sink.py` (+61): `persist_minted` at link time uses `save_linked_identity`.
- sha: `ea23a57a9` · 2026-09-16 · Jesus Lara · TASK-082 — `parrot/services/vault_token_sync.py` (+97/-?) typed `VaultTokenRead`, per-instance SessionVault cache invalidated on write/delete.
- sha: `9428e08b1` · 2026-07-23 · Jesus · fix(msteams): resolve APP_TENANTID from env, unify … (services, Teams tenant config).

## Notes

- Identity model as of git: `auth.user_identities` rows hold **both** channel mappings (telegram / msteams / slack → `nav_user_id`, non-secret) **and** the Jira provider row (sealed tokens + `account_id/cloud_id/site_url`). `nav_user_id` is a bigint; AAD GUIDs and composite `team:user` strings were previously (wrongly) written there.
- Answers brainstorm R1 "Telegram login links to a platform user": yes — the Telegram login flow is the one flow that puts `nav_user_id` into the OAuth state (`6aa0e639d` message); Slack/Teams first-link may have no owner.
- [cross-lane: type=read, intent=read `identity_mapping.py` for the exact upsert/lookup API (`upsert_identity`, `get_by_provider`, provider names) and the bigint constraint]
- [cross-lane: type=wiki_page, intent=open ledger issues 2e85cce93cab, 187ce3fe3b93, a671f989e8e7, 0115386145f2 — still-open identity/vault debt that S-1/S-2 must not re-break]
