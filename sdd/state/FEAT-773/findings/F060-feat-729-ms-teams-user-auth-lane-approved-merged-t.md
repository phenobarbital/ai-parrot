---
id: F060
query_id: Q007
type: wiki_page
intent: "Read spec: MS Teams user authentication lane — decides whether S-3b already has a Teams auth channel."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FW-007]
---

# F060 — FEAT-729 MS Teams user auth lane (approved, merged to dev PR #1787, 9 tasks done/done-with-issues): `MSTeamsAuthStrategy` via Bot Framework Token Service + `TokenExchangeClient` (core) → Navigator session; `/login /logout /whoami`; `aad_object_id` is the Teams session key

## Summary

S-3b's premise ("Teams has no auth channel yet") is stale. FEAT-729 (2026-10-22/23) built: `MSTeamsUserSession` + `MSTeamsSessionStore` (`msteams/auth.py`, keyed `aad_object_id or from_property.id`, carries `nav_user_id`, `nav_session_token`, per-user `tool_manager`/`user_agent`, `post_login_ran`); `TokenExchangeClient` (`parrot/auth/token_exchange.py`, core, channel-agnostic: `POST {auth_url}` with `X-Auth-Method: TokenExchangeAuth`, maps `user_not_found`/`backend_not_loaded`); `MSTeamsAuthStrategy` (adapter `get_user_token` / `exchange_token` / `get_oauth_sign_in_link` + `OAuthCard`, `signin/verifyState` & `signin/tokenExchange` invokes); `/login`, `/logout`, `/whoami` commands; wrapper gate building `UserContext(channel="msteams", user_id=nav_user_id)` and driving `AbstractBot.post_login`/`clone_for_user`; `MSTeamsAgentConfig` gained `oauth_connection_name`, `auth_required`, `navigator_auth_url`, `prefer_id_token`. The PoC proved `provider_user_id` from the exchange == Entra `oid` == `aad_object_id` — the identity bridge. Non-goals: hand-rolled OBO, the separate `msagentsdk` lane (already has `BFTokenServiceResolver`), enabling `TokenExchangeAuth` in prod config (ops). Proactive messaging for Jira callbacks already existed from FEAT-225 (`MSTeamsOAuthNotifier`, conversation_reference in `extra_state`).

## Citations

- path: `sdd/specs/msteams-user-auth-lane.spec.md`
  lines: n/a
  symbol: FEAT-729 §1–§3, §6 (anchors `wrapper.py:460/:675/:1025` raw Teams id context dicts; `msteams/commands/jira_commands.py:116 _get_user_id`; `auth/session_identity.py:90 resolve_user_id`; `auth/context.py:39 UserContext`; `bots/abstract.py:4561 post_login`, `:4583 clone_for_user`)
  wiki_page_id: file:sdd/specs/msteams-user-auth-lane.spec.md
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/auth.py`
  lines: n/a
  symbol: `MSTeamsUserSession`, `MSTeamsSessionStore`, `MSTeamsAuthStrategy`, `user_key()`
- path: `packages/ai-parrot/src/parrot/auth/token_exchange.py`
  lines: n/a
  symbol: `TokenExchangeClient.exchange(provider, token, token_type, id_token) -> TokenExchangeResult`
- path: `packages/ai-parrot-integrations/src/parrot/integrations/msteams/commands/auth_commands.py`
  lines: n/a
  symbol: `register_auth_commands(router, strategy)` — `/login`, `/logout`, `/whoami`
- path: `packages/ai-parrot/src/parrot/auth/session_identity.py`
  lines: n/a
  symbol: `resolve_user_id(request, session)` → canonical Navigator id
- path: `sdd/tasks/index/msteams-user-auth-lane.json`
  lines: n/a
  symbol: TASK-4659..4667; 4664/4665 `done-with-issues`; completed 2026-10-23T16:13

## Notes

Teams principal mapping for S-3b therefore exists: `aad_object_id` ↔ Navigator `user_id` via `TokenExchangeAuth`. TASK-4665 (E2E tests) is done-with-issues — the codebase/git lane may check its Completion Note. `[cross-lane: type=git_log, intent=confirm FEAT-729 merge commit on dev (PR #1787, dev @ 899d1fe59) and TASK-4665 completion note]`.
