---
id: F073
query_id: Q014
type: wiki_page
intent: "Follow-up: Jira callback route + Telegram combined flow — how completion reaches the channel today."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: FW-014
depth: 1
merged_from: [FW-020]
---

# F073 — `auth/routes.py::jira_oauth_callback` dispatches by `state_payload["channel"]` and notifies channels by DIRECT in-process calls (`app['jira_oauth_notifier']`, `telegram_jira_session_stamper`, Slack/Teams handlers); the Telegram combined login (`JiraPostAuthProvider`) carries `nav_user_id` in `extra_state` and writes identity rows but no longer writes tokens

## Summary

`jira_oauth_callback` (`GET /api/auth/jira/callback`) requires `app['jira_oauth_manager']`; handles `?error=` first via `_handle_oauth_error` (consumes nonce, routes Slack/Teams failure notifications); then `manager.handle_callback(code, state)`; then branches: `web` → `_handle_web_callback` (FW-011); `slack` → `handle_slack_jira_callback`; `msteams` → `handle_msteams_jira_callback`; `telegram`/absent → `app['telegram_jira_session_stamper'](telegram_user_id, token_set)` + fire-and-forget `TelegramOAuthNotifier.notify_connected(chat_id, …)` using `extra.chat_id`, and a static HTML success page. `JiraPostAuthProvider` (Telegram, `post_auth_jira.py`) implements the `PostAuthProvider` protocol: `build_auth_url` stashes `{flow:"combined", telegram_id, telegram_username, callback_base_url, nav_user_id?, nav_display_name?, nav_email?}` in `extra_state` with `channel="telegram"`, `user_id=str(telegram_id)`; `handle_result` resolves `nav_user_id` (primary auth payload → extra → session), writes `telegram` + `jira` identity rows via `IdentityMappingService`, stamps `session.set_jira_authenticated(...)`; since FEAT-735 it does NOT store tokens (`vault_sync` retained only for disconnect). So the Telegram→Navigator link exists (`TelegramUserSession.nav_user_id` from the primary auth strategy) and is persisted as the `telegram` identity row — R1 confirmed.

## Citations

- path: `packages/ai-parrot/src/parrot/auth/routes.py`
  lines: n/a
  symbol: `jira_oauth_callback`, `_handle_oauth_error`, `_handle_web_callback`, `_notify_telegram`, `setup_jira_oauth_routes`
  wiki_page_id: file:packages/ai-parrot/src/parrot/auth/routes.py
  excerpt: |
    channel = state_payload.get("channel", "telegram")
    if channel == "web": return await _handle_web_callback(request, token_set, state_payload)
    if channel == "slack": ... handle_slack_jira_callback(request, token_set, state_payload)
    if channel == "msteams": ... handle_msteams_jira_callback(request, token_set, state_payload)
    stamper = request.app.get("telegram_jira_session_stamper")
    notifier = request.app.get("jira_oauth_notifier")
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py`
  lines: n/a
  symbol: `JiraPostAuthProvider` (`provider_name="jira"`, `build_auth_url`, `handle_result`, `_write_identity_records`)
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/telegram/post_auth_jira.py (score=0.43)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py`
  lines: n/a
  symbol: `TelegramUserSession` (`nav_user_id`, `nav_display_name`, `nav_email`, `set_jira_authenticated`), `AbstractAuthStrategy` (Basic/Azure/Google/OAuth2/Composite), `NavigatorAuthClient`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/telegram/auth.py (score=0.83)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/core/auth/post_auth.py`
  lines: n/a
  symbol: `PostAuthProvider` protocol, `PostAuthRegistry` (FEAT-225 M1 lift)

## Notes

The callback handler, the Telegram notifier and the Telegram bot must share one aiohttp `app` (same process) for `app['jira_oauth_notifier']` to work — this is the coupling Spike S4 cares about. `[cross-lane: type=grep, intent=where app['jira_oauth_notifier'] / telegram_jira_session_stamper are set (telegram/wrapper.py) and whether the Telegram bot runs in the BotManager process]`.
