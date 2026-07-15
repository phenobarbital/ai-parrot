---
type: Wiki Entity
title: PostAuthAction
id: class:parrot.integrations.telegram.models.PostAuthAction
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for a secondary authentication action to chain after
---

# PostAuthAction

Defined in [`parrot.integrations.telegram.models`](../summaries/mod:parrot.integrations.telegram.models.md).

```python
class PostAuthAction
```

Configuration for a secondary authentication action to chain after
primary authentication (e.g., Jira OAuth2 3LO after BasicAuth).

Attributes:
    provider: Name of the secondary auth provider (e.g., "jira",
              "confluence", "github"). Must match a registered
              ``PostAuthProvider`` at runtime.
    required: If True, failure of this secondary auth rolls back the
              primary authentication session. If False (default), the
              primary session remains authenticated even on failure.
