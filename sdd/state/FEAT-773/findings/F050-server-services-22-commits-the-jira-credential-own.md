---
id: F050
query_id: Q061
type: git_log
intent: "History: identity + vault services churn (FEAT-729/735) — recency of the owner decision."
executed_at: 2026-10-30T12:05:12Z
duration_ms: 800
parent_id: null
depth: 0
merged_from: [FG-002]
---

# F050 — server/services: 22 commits; the Jira-credential owner decision landed 2026-10-23 (FEAT-729 + FEAT-735)

## Summary

22 commits (2026-07-23 → 2026-10-23) on `packages/ai-parrot-server/src/parrot/services/`. Two themes: commcenter/notify work (Emmanuel Arroyo, Aug 2026, unrelated) and the **identity + vault** wave by Jesus on 2026-10-23: FEAT-729 **msteams-user-auth-lane** (TASK-4664: identity writes via `IdentityStore` for Jira + fixed partial-index SQL for channel providers; TASK-4667: Teams carries the Navigator user id separately from the AAD object id in the Jira OAuth state, fail-closed on non-numeric nav id) and FEAT-735 **services-vault-token-sync-tech-debt** (TASK-4668/4669: new `IdentityVaultCredentialSink`). `IdentityMappingService` (`identity_mapping.py`) grew +187/-41 in TASK-4664 and now rejects a non-numeric `nav_user_id` on both write paths; a follow-up fix (`13838cfb4`) corrected a jsonb stamping bug that silently dropped `account_id/cloud_id/site_url` from Jira identity rows (fixed with `$2::text::jsonb`), validated against real Postgres on navigator-auth 0.28.8. `VaultTokenSync` last changed 2026-09-16 (TASK-082, typed reads). The owner decision is one week old at research time — fresh and still carrying open issues (2e85cce93cab, 187ce3fe3b93, a671f989e8e7 referenced in messages).

## Citations

(none)

## Notes

- Identity model as of git: `auth.user_identities` rows hold **both** channel mappings (telegram / msteams / slack → `nav_user_id`, non-secret) **and** the Jira provider row (sealed tokens + `account_id/cloud_id/site_url`). `nav_user_id` is a bigint; AAD GUIDs and composite `team:user` strings were previously (wrongly) written there.
- Answers brainstorm R1 "Telegram login links to a platform user": yes — the Telegram login flow is the one flow that puts `nav_user_id` into the OAuth state (`6aa0e639d` message); Slack/Teams first-link may have no owner.
- [cross-lane: type=read, intent=read `identity_mapping.py` for the exact upsert/lookup API (`upsert_identity`, `get_by_provider`, provider names) and the bigint constraint]
- [cross-lane: type=wiki_page, intent=open ledger issues 2e85cce93cab, 187ce3fe3b93, a671f989e8e7, 0115386145f2 — still-open identity/vault debt that S-1/S-2 must not re-break]
