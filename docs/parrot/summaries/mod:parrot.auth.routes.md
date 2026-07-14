---
type: Wiki Summary
title: parrot.auth.routes
id: mod:parrot.auth.routes
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: HTTP routes for OAuth callbacks.
relates_to:
- concept: func:parrot.auth.routes.jira_oauth_callback
  rel: defines
- concept: func:parrot.auth.routes.setup_jira_oauth_routes
  rel: defines
- concept: mod:parrot.auth.jira_oauth
  rel: references
- concept: mod:parrot.auth.oauth2.service
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.integrations.msteams.oauth_callback
  rel: references
- concept: mod:parrot.integrations.slack.oauth_callback
  rel: references
- concept: mod:parrot.integrations.telegram.jira_commands
  rel: references
---

# `parrot.auth.routes`

HTTP routes for OAuth callbacks.

This module exposes the aiohttp route that Atlassian's consent page
redirects to after a user authorizes their Jira account:

- ``GET /api/auth/jira/callback?code=...&state=...``

The handler validates the CSRF state nonce, exchanges the code for
tokens via :class:`JiraOAuthManager`, and renders a browser-friendly
HTML success/error page.  The manager must be stored on
``app['jira_oauth_manager']`` at application startup.

Optionally, a :class:`TelegramOAuthNotifier` stored on
``app['jira_oauth_notifier']`` receives a fire-and-forget notification
after successful callbacks that originated from Telegram (i.e. the
authorization URL included ``extra_state={"chat_id": ...}``).

For web-channel OAuth2 3LO flows the callback instead persists the
credential via :class:`~parrot.integrations.oauth2.service.IntegrationsService`
and renders a ``postMessage`` HTML page that signals the opener popup.

## Functions

- `async def jira_oauth_callback(request: web.Request) -> web.Response` — Handle ``GET /api/auth/jira/callback``.
- `def setup_jira_oauth_routes(app: web.Application) -> None` — Attach the Jira OAuth callback route to *app*.
