---
id: FW-011
query_id: Q011
type: wiki_page
intent: "Read task: TASK-987 OAuth callback web-channel branch + templates — web callback/success page state."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
---

# FW-011 — TASK-987 (FEAT-144, done 2026-05-05): `/api/auth/jira/callback` has a `channel == "web"` branch rendering `web_oauth_success.html` / `web_oauth_error.html` that `postMessage`s `{type:"ai-parrot-oauth-callback", provider, success, account_id, display_name}` to `window.opener` with a server-validated `target_origin` from `WEB_OAUTH_ALLOWED_ORIGINS`

## Summary

The brainstorm's "callback renders a success page that postMessages to the opener and closes" is already implemented for the Jira route (`parrot/auth/routes.py::_handle_web_callback`) and generically (`parrot/auth/oauth2_routes.py::_handle_web_callback`). Templates live in `packages/ai-parrot/src/parrot/auth/templates/`. The web branch persists the credential via `IntegrationsService.persist_credential(user_id, provider, token_set)` into DocumentDB `users_integrations` (a *metadata* row — account_id/display_name/email/scopes/cloud_id/site_url — not the token). `return_origin` is validated against `WEB_OAUTH_ALLOWED_ORIGINS` (`parrot/conf.py`, FEAT-144 M11). Error branch `_handle_oauth_error` consumes the nonce and dispatches to Slack/Teams handlers for failure notifications.

## Citations

- path: `sdd/tasks/completed/TASK-987-oauth-callback-web-branch.md`
  lines: n/a
  symbol: TASK-987 (status done, FEAT-144 M7)
  wiki_page_id: ledger::task:TASK-987
- path: `packages/ai-parrot/src/parrot/auth/routes.py`
  lines: n/a
  symbol: `_handle_web_callback(request, token_set, state_payload)`, `_WEB_SUCCESS_TMPL`, `_WEB_ERROR_TMPL`, `jira_oauth_callback` channel dispatch (web/slack/msteams/telegram), `setup_jira_oauth_routes` (+ `navigator_auth.conf.exclude_list`)
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/routes.py
- path: `packages/ai-parrot/src/parrot/auth/templates/web_oauth_success.html`
  lines: n/a
  symbol: postMessage + window.close template
- path: `packages/ai-parrot/src/parrot/auth/templates/web_oauth_error.html`
  lines: n/a
  symbol: error template (`error`, `target_origin`)
- path: `packages/ai-parrot/src/parrot/conf.py`
  lines: n/a
  symbol: `WEB_OAUTH_ALLOWED_ORIGINS`
  wiki_page_id: file:packages/ai-parrot/src/parrot/conf.py

## Notes

Completion is NOT event-driven: the callback calls channel notifiers directly (`app['jira_oauth_notifier']` Telegram, `handle_slack_jira_callback` DM, `handle_msteams_jira_callback` proactive) — this is the direct-call coupling the brainstorm wants to replace with `connection.*` bus events. For web there is no server push at all; the popup `postMessage` is the only completion signal (FEAT-144 non-goal: multi-tab sync).
