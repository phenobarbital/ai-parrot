---
type: Wiki Entity
title: ResolvedTeamsUser
id: class:parrot.integrations.msteams.graph.ResolvedTeamsUser
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result of a successful Graph email-to-AAD resolution.
---

# ResolvedTeamsUser

Defined in [`parrot.integrations.msteams.graph`](../summaries/mod:parrot.integrations.msteams.graph.md).

```python
class ResolvedTeamsUser(BaseModel)
```

Result of a successful Graph email-to-AAD resolution.

Attributes:
    aad_object_id: Azure AD object ID (GUID) for the user.
    upn: User Principal Name (often the same as email for cloud accounts).
    email: The email address that was resolved.
    service_url: Optional Bot Framework service URL associated with the
        user (populated from the ConversationReference cache, not from
        Graph directly).
