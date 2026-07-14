---
type: Wiki Entity
title: JiraTokenSet
id: class:parrot.auth.jira_oauth.JiraTokenSet
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-user Jira OAuth 2.0 token set persisted in Redis.
---

# JiraTokenSet

Defined in [`parrot.auth.jira_oauth`](../summaries/mod:parrot.auth.jira_oauth.md).

```python
class JiraTokenSet(BaseModel)
```

Per-user Jira OAuth 2.0 token set persisted in Redis.

## Methods

- `def is_expired(self) -> bool` — Return True if the access token has expired (with 60s leeway).
- `def api_base_url(self) -> str` — Return the Atlassian REST API base URL for this cloud_id.
