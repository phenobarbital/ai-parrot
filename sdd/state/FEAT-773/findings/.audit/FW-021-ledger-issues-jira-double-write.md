---
id: FW-021
query_id: Q003
type: wiki_query
intent: "Follow-up: ledger status of the Jira credential double-write and identity issues."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: FW-003
depth: 1
---

# FW-021 — Ledger: `issue:50a31674e4f2` closed (superseded), `issue:2e85cce93cab` closed (resolved by FEAT-735 TASK-4668), `issue:0115386145f2` closed (TASK-4664), `issue:187ce3fe3b93` closed (TASK-4667), `issue:e2221d566081` STILL OPEN (stale — its ask was delivered by FEAT-735 TASK-4671)

## Summary

`wikitoolkit ledger show` on the five issues: (1) `50a31674e4f2` "Jira credential in two stores" — closed 2026-10-23 as superseded by (2). (2) `2e85cce93cab` "two writers, no agreed owner" — escalated to FEAT-735 (three stores found: Redis live read path, Session Vault badge copy never refreshed, IdentityStore copy with no reader), closed by `/sdd-done` 2026-10-23T21:47 resolved_by TASK-4668. (3) `0115386145f2` 42P10 — closed by TASK-4664 (also found asyncdb pool swallowing errors and bigint bind). (4) `187ce3fe3b93` Teams AAD GUID → bigint — closed; TASK-4667 separates `nav_user_id` state key from the AAD id, callback fails closed. (5) `e2221d566081` "Retire VaultTokenSync Jira token write after IdentityStore adoption" — status `open`, kind tech_debt, minor, about `telegram/post_auth_jira.py`; its content (remove `_store_in_vault`) was implemented by FEAT-735 TASK-4671 per the current `post_auth_jira.py` docstring, so it is a stale open issue the proposal can close or cite.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py`
  lines: n/a
  symbol: `JiraPostAuthProvider` docstring ("Since FEAT-735 … this provider no longer stores tokens here")
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py
- path: `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py`
  lines: n/a
  symbol: `VaultTokenSync` (about-symbol of issues 50a3…/2e85…)
  wiki_page_id: ledger::issue:2e85cce93cab
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/oauth_callback.py`
  lines: n/a
  symbol: `handle_msteams_jira_callback` — fails closed on missing/non-numeric nav id (TASK-4667)
  wiki_page_id: ledger::issue:187ce3fe3b93
- path: `packages/ai-parrot-server/src/parrot/services/identity_mapping.py`
  lines: n/a
  symbol: `IdentityMappingService.upsert_identity` rejects non-numeric `nav_user_id` (TASK-4667)
  wiki_page_id: ledger::issue:187ce3fe3b93

## Notes

Open related: `issue:a671f989e8e7` (Slack composite id) resolved by TASK-4666 (write skipped); `issue:f010a27ccadd` NetSuite factory `token_store` param; `issue:b5e64d019469` Jira OAuth helpers echo raw response bodies. The proposal should treat `issue:e2221d566081` as closable evidence, not as a gap.
