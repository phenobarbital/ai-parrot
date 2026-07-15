---
type: Wiki Entity
title: TeamsCardRenderer
id: class:parrot.integrations.msteams.hitl_cards.TeamsCardRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Pure renderer: :class:`~parrot.human.models.HumanInteraction` → Adaptive
  Card dict.'
---

# TeamsCardRenderer

Defined in [`parrot.integrations.msteams.hitl_cards`](../summaries/mod:parrot.integrations.msteams.hitl_cards.md).

```python
class TeamsCardRenderer
```

Pure renderer: :class:`~parrot.human.models.HumanInteraction` → Adaptive Card dict.

All methods are synchronous (no I/O).  The returned dict is JSON-
serialisable and can be passed directly to ``CardFactory.adaptive_card``
or used in an ``Attachment`` body.

Args:
    render_reject_button: When ``True``, policy-bound interactions receive
        an "↑ Escalar" submit action.  Matches
        ``TeamsHumanChannel.render_reject_button``.

## Methods

- `def render(self, interaction: HumanInteraction, render_reject_button: Optional[bool]=None) -> Dict[str, Any]` — Render an Adaptive Card for the given interaction.
- `def render_disabled(self, interaction_id: str, reason: str='expired') -> Dict[str, Any]` — Render a disabled/expired card variant for cancel/update.
