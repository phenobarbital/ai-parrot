---
type: Wiki Summary
title: parrot.integrations.telegram.combined_callback
id: mod:parrot.integrations.telegram.combined_callback
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Combined BasicAuth + secondary OAuth callback for the Telegram WebApp.
relates_to:
- concept: func:parrot.integrations.telegram.combined_callback.combined_auth_callback_handler
  rel: defines
- concept: func:parrot.integrations.telegram.combined_callback.setup_combined_auth_routes
  rel: defines
- concept: mod:parrot.integrations.telegram.oauth2_callback
  rel: references
---

# `parrot.integrations.telegram.combined_callback`

Combined BasicAuth + secondary OAuth callback for the Telegram WebApp.

After the login page completes BasicAuth and redirects the user to a
secondary OAuth provider (Jira in the current feature scope), the provider
redirects the browser back here. This endpoint returns HTML that packages
the ``code`` / ``state`` into a ``WebApp.sendData`` payload keyed under the
provider name (``jira`` by default) so ``TelegramAgentWrapper.
handle_web_app_data`` can detect the combined flow.

The BasicAuth result itself is carried across the Jira redirect via the
``extra_state`` parameter of ``JiraOAuthManager.create_authorization_url``
(stored alongside the CSRF nonce in Redis). This handler does NOT look up
or consume the nonce; it simply forwards ``code`` + ``state`` to the
wrapper, which has the Redis client and will resolve it there.

## Functions

- `async def combined_auth_callback_handler(request: web.Request) -> web.Response` — Handle the combined BasicAuth + secondary OAuth redirect.
- `def setup_combined_auth_routes(app: web.Application, path: str=COMBINED_CALLBACK_PATH) -> None` — Register the combined callback route and exclude it from auth.
