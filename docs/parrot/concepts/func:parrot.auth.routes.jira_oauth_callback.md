---
type: Concept
title: jira_oauth_callback()
id: func:parrot.auth.routes.jira_oauth_callback
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handle ``GET /api/auth/jira/callback``.
---

# jira_oauth_callback

```python
async def jira_oauth_callback(request: web.Request) -> web.Response
```

Handle ``GET /api/auth/jira/callback``.

Validates required query parameters, delegates the exchange to
:class:`JiraOAuthManager`, and renders an HTML page for the browser.
After a successful exchange, optionally fires a Telegram notification
via the :class:`TelegramOAuthNotifier` stored on ``app['jira_oauth_notifier']``.
