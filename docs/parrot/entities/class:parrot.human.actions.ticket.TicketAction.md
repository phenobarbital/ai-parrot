---
type: Wiki Entity
title: TicketAction
id: class:parrot.human.actions.ticket.TicketAction
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Dispatches ticket-creation escalation actions to Zammad (V1).
relates_to:
- concept: class:parrot.human.actions.base.EscalationAction
  rel: extends
---

# TicketAction

Defined in [`parrot.human.actions.ticket`](../summaries/mod:parrot.human.actions.ticket.md).

```python
class TicketAction(EscalationAction)
```

Dispatches ticket-creation escalation actions to Zammad (V1).

The backend is selected by ``tier.action_metadata["kind"]`` (or the legacy
``"platform"`` key).  Supported kinds:

- ``"zammad"`` → :class:`~parrot.human.actions.backends.ZammadBackend`

Legacy ``platform="jira"`` is treated as ``"zammad"`` with a warning
(Jira is not in V1).

When a backend fails, the exception is caught and a dict with
``error=True`` is returned so the manager can advance to the next tier.

Args:
    zammad_cfg: Keyword arguments forwarded to :class:`ZammadBackend.__init__`.

## Methods

- `async def execute(self, interaction, tier) -> Dict[str, Any]` — Dispatch to the appropriate ticket backend.
