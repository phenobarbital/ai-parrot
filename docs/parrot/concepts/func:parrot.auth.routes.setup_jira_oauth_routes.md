---
type: Concept
title: setup_jira_oauth_routes()
id: func:parrot.auth.routes.setup_jira_oauth_routes
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Attach the Jira OAuth callback route to *app*.
---

# setup_jira_oauth_routes

```python
def setup_jira_oauth_routes(app: web.Application) -> None
```

Attach the Jira OAuth callback route to *app*.

Call this once at application startup, after the
:class:`JiraOAuthManager` has been stored at ``app['jira_oauth_manager']``.
Optionally store a :class:`TelegramOAuthNotifier` at
``app['jira_oauth_notifier']`` to enable post-callback Telegram messages.
