---
type: Wiki Entity
title: ZammadBackend
id: class:parrot.human.actions.backends.zammad.ZammadBackend
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Creates a support ticket in a Zammad instance.
relates_to:
- concept: class:parrot.human.actions.backends.base.ActionBackend
  rel: extends
---

# ZammadBackend

Defined in [`parrot.human.actions.backends.zammad`](../summaries/mod:parrot.human.actions.backends.zammad.md).

```python
class ZammadBackend(ActionBackend)
```

Creates a support ticket in a Zammad instance.

Args:
    base_url: The base URL of the Zammad instance,
        e.g. ``"https://support.example.com"``.
    api_token: Zammad API token for ``Authorization: Token token=...`` auth.
    default_group: Fallback group/queue name when ``action_metadata`` does
        not specify one.
    timeout_seconds: HTTP request timeout (default 10s).

Example ``action_metadata`` consumed by this backend::

    {
        "kind": "zammad",
        "queue": "Support",
        "title_template": "HITL Escalation: {interaction.question[:60]}",
    }

## Methods

- `async def execute(self, interaction: 'HumanInteraction', tier: 'EscalationTier') -> Dict[str, Any]` — Create a Zammad ticket for the given interaction.
