---
type: Wiki Entity
title: AuthRequiredEnvelope
id: class:parrot.auth.oauth2.models.AuthRequiredEnvelope
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Single-body response returned by ``AgentTalk`` when a tool raises
---

# AuthRequiredEnvelope

Defined in [`parrot.auth.oauth2.models`](../summaries/mod:parrot.auth.oauth2.models.md).

```python
class AuthRequiredEnvelope(BaseModel)
```

Single-body response returned by ``AgentTalk`` when a tool raises
``AuthorizationRequired``.

The frontend detects ``type == "auth_required"`` and renders a
``ConnectIntegrationPill`` inline in the chat.

Attributes:
    type: Discriminator literal — always ``"auth_required"``.
    provider: Provider identifier, e.g. ``"jira"``.
    tool_name: Name of the tool that triggered the exception.
    auth_url: Authorization URL to open in the popup (may be absent if the
        provider could not generate one at exception time).
    scopes: Scopes needed by the provider.
    message: Human-readable explanation surfaced in the chat UI.
