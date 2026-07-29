---
type: Concept
title: escalate_option()
id: func:parrot.human.channels.base.escalate_option
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the standardised "↑ Escalar" choice option.
---

# escalate_option

```python
def escalate_option() -> 'ChoiceOption'
```

Return the standardised "↑ Escalar" choice option.

Channels that opt in to the reject button append this option to their
rendered UI when the interaction is policy-bound
(``interaction.policy is not None``).

Returns:
    A :class:`~parrot.human.models.ChoiceOption` with
    ``key=ESCALATE_OPTION_KEY`` and ``label="↑ Escalar"``.
