---
id: FC-056
query_id: Q034-F1
type: read
intent: "Follow-up: Telegram generic oauth2_callback.py (login) and wrapper wiring of the post-auth registry."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: FC-015
depth: 1
---

# FC-056 — telegram/oauth2_callback.py is the WebApp LOGIN callback (returns HTML that calls Telegram WebApp.sendData), mounted at /oauth2/callback by setup_oauth2_routes — not a tool-credential callback; wrapper registers JiraPostAuthProvider when post_auth_actions includes jira and app has authdb/redis

## Summary

`telegram/oauth2_callback.py` (206): `oauth2_callback_handler` renders a page embedding `telegram-web-app.js` and passes code/state back via `WebApp.sendData()`; `setup_oauth2_routes(app, path="/oauth2/callback")`. `telegram/wrapper.py:595-625`: if `post_auth_actions` includes `jira` and `app['authdb']`/`app['database']` + `app['redis']` exist, builds `IdentityMappingService(db_pool)`, `VaultTokenSync(db_pool, redis_client)`, `JiraPostAuthProvider(...)` and registers it. `:1280-1300` `_build_permission_context` sets `channel="telegram"`, `user_id=telegram_id`, `extra['chat_id']`, `extra['telegram_bot_id']`.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/oauth2_callback.py`
  lines: 138-206
  symbol: `oauth2_callback_handler / setup_oauth2_routes`
  excerpt: |
    async def oauth2_callback_handler(request) -> web.Response  # HTML -> WebApp.sendData()
    def setup_oauth2_routes(app, path: str = "/oauth2/callback")
- path: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`
  lines: 1280-1300
  symbol: `TelegramAgentWrapper._build_permission_context docstring`
  excerpt: |
    The context carries channel="telegram" and the telegram_id as the session user_id ... When chat_id is supplied it is added to extra[chat_id]

## Notes

Name collision: there are two `setup_oauth2_routes` (core `parrot.auth.oauth2_routes` for tool credentials; telegram for WebApp login). PermissionContext.user_id on Telegram = raw telegram_id (brainstorm §10 last bullet confirmed).
