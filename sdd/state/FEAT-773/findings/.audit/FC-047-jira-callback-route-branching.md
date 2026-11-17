---
id: FC-047
query_id: Q021-F1
type: read
intent: "Follow-up: read parrot/auth/routes.py — the Jira callback route and its per-channel branching."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-002
depth: 1
---

# FC-047 — GET /api/auth/jira/callback dispatches by state_payload['channel']: web -> IntegrationsService.persist_credential + postMessage page; slack/msteams -> integrations handlers; telegram (default) -> session stamper + TelegramOAuthNotifier on app['jira_oauth_notifier']

## Summary

351 lines. `_handle_web_callback` (:84-166) persists via `IntegrationsService().persist_credential(user_id, provider, token_set)` and renders the postMessage page. `jira_oauth_callback` (:232-331): after `handle_callback`, `channel = state_payload.get("channel", "telegram")` (default telegram for back-compat); `web` → web handler; `slack` → `handle_slack_jira_callback`; `msteams` → `handle_msteams_jira_callback`; telegram → `request.app.get("telegram_jira_session_stamper")(telegram_user_id, token_set)` then fire-and-forget `_notify_telegram(notifier, chat_id, …)` using `app.get("jira_oauth_notifier")`. Consent-denial path (:187-229) routes `?error=` similarly. `setup_jira_oauth_routes(app)` (:333-351) mounts + exclude_list.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/routes.py`
  lines: 277-291
  symbol: `jira_oauth_callback (dispatch)`
  excerpt: |
    channel = state_payload.get("channel", "telegram")
    if channel == "web": ...
    if channel == "slack": from parrot.integrations.slack.oauth_callback import handle_slack_jira_callback
    if channel == "msteams": from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback
- path: `packages/ai-parrot/src/parrot/auth/routes.py`
  lines: 296-322
  symbol: `jira_oauth_callback (telegram)`
  excerpt: |
    stamper = request.app.get("telegram_jira_session_stamper")
    notifier = request.app.get("jira_oauth_notifier")
    asyncio.create_task(_notify_telegram(notifier, ...))
- path: `packages/ai-parrot/src/parrot/auth/routes.py`
  lines: 333-351
  symbol: `setup_jira_oauth_routes`
  excerpt: |
    app.router.add_get("/api/auth/jira/callback", jira_oauth_callback)
    exclude_list.append("/api/auth/jira/callback")

## Notes

Completion→channel is a direct in-process dispatch keyed by `state.channel`; core `parrot.auth.routes` lazily imports integrations modules (core→integrations dependency the brainstorm constraint 'core must not depend on integrations' would forbid). Telegram notification requires `app['jira_oauth_notifier']` to be in the same process as the callback.
