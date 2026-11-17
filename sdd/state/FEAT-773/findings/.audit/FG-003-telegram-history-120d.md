---
id: FG-003
query_id: Q062
type: git_log
intent: "History: Telegram jira commands — stability of the production flow."
executed_at: 2026-10-30T12:05:12Z
duration_ms: 700
parent_id: null
depth: 0
---

# FG-003 — telegram integration: 40 commits in 120 days; Jira flow stable except the 2026-10-23 post-auth rewrite (TASK-4664/4671)

## Summary

40 commits (2026-07-06 → 2026-10-28) on `packages/ai-parrot-integrations/src/parrot/integrations/telegram/`, all Jesus / Jesus Lara; ~10 are black-formatting apply/revert pairs (2026-08-23). Auth-relevant commits: **`8701ccc0b` "Telegram multi-auth support" (2026-08-31)** — new `telegram/auth.py` (+313) and `static/login_multi.html` (+243), a multi-provider login page; **TASK-4664 (`a11d28521`, 2026-10-23)** — `post_auth_jira.py` writes the Jira identity through `IdentityStore`; **TASK-4671 (`f23af0cbd`, 2026-10-23)** — `JiraPostAuthProvider` lost its two redundant writers: `_store_in_vault` (flat `jira:*` Session-Vault keys) and the `token=` argument on the jira upsert were removed (-56 lines); the commit message states "no reader of the Jira vault keys remains anywhere" and that the telegram/jira mapping rows are kept. `jira_commands.py` itself does not appear in any commit of the window (not in the stat output), i.e. the `/connect_jira` command surface is unchanged since before July 2026. Also: `d29bd59d4` "wip: event bus" (2026-07-20) touched `wrapper.py` (+9/-5) — eventbus wiring in the Telegram wrapper exists at least as a WIP.

## Citations

- sha: `8701ccc0b` · 2026-08-31 · Jesus · Telegram multi-auth support
  files: `telegram/auth.py` (+313 new), `telegram/models.py` (+51/-?), `telegram/static/login_multi.html` (+243), `telegram/wrapper.py` (+13).
- sha: `a11d28521` · 2026-10-23 · Jesus · feat(msteams-user-auth-lane): TASK-4664
  files: `telegram/post_auth_jira.py` (+26) — Jira identity write via IdentityStore.
- sha: `f23af0cbd` · 2026-10-23 · Jesus Lara · feat(services-vault-token-sync-tech-debt): TASK-4671 — retire the two redundant Jira writers
  files: `telegram/post_auth_jira.py` (+12/-56) — removed `_store_in_vault`, `_build_token_response`, `token=` on jira upsert; kept jira + telegram mapping upserts; `vault_sync` kept on the constructor for the disconnect path.
- sha: `d29bd59d4` · 2026-07-20 · Jesus · wip: event bus
  files: `telegram/wrapper.py` (+9/-5).
- sha: `fe1f307bd` · 2026-07-08 · Jesus · agent integration of commands
  files: `telegram/wrapper.py` (+3/-15).
- sha: `4ea69592b` · 2026-09-23 · Jesus Lara · fix(telegram): gate /add_mcp DocumentDB persistence … (MCP persistence in Telegram).
- sha: `7b6dac4ac` · 2026-10-15 · Jesus Lara · TASK-4347 — `telegram/knowledge_upload.py` pre-authorize (unrelated to OAuth).
- sha: `58070afa5`…`31ca6e958` · 2026-10-28 · suggestion chips (FEAT-752) — unrelated.

## Notes

- Production-flow stability: the Telegram `/connect_jira` handlers were not modified in 120 days; the post-auth persistence path was rewritten one week ago (writer consolidation onto the Identity Vault). A migration spec (S-2) must start from the post-TASK-4671 shape, not the brainstorm's "Redis `jira:oauth:<channel>:<user_id>`" picture — though that Redis key may still be the `JiraOAuthManager` token cache (the Session-Vault `jira:*` copy is what was removed, not necessarily the manager's Redis keys).
- [cross-lane: type=read, intent=read `telegram/auth.py` + `login_multi.html` — multi-provider login page may already be the channel→principal link UI]
- [cross-lane: type=grep, intent=in `telegram/wrapper.py` find the eventbus usage introduced by `d29bd59d4` (publish? subscribe?)]
- [cross-lane: type=grep, intent=confirm whether `JiraOAuthManager` Redis keys (`jira:oauth:…`) are still written/read after TASK-4671]
