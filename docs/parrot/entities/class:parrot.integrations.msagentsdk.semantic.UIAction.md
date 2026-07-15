---
type: Wiki Entity
title: UIAction
id: class:parrot.integrations.msagentsdk.semantic.UIAction
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A card action button.
---

# UIAction

Defined in [`parrot.integrations.msagentsdk.semantic`](../summaries/mod:parrot.integrations.msagentsdk.semantic.md).

```python
class UIAction(BaseModel)
```

A card action button.

Exactly one of ``prompt_template`` or ``url`` must be set. Actions with
``prompt_template`` render as ``Action.Submit`` (messageBack) and re-enter
the agent's ``ask()`` pipeline as natural language. Actions with ``url``
render as ``Action.OpenUrl``.

Attributes:
    title: The button label shown on the card.
    prompt_template: Natural-language prompt template re-entering
        ``ask()``, e.g. ``"Show details for order {id}"``. Mutually
        exclusive with ``url``.
    params: Values used to fill ``prompt_template`` placeholders.
    url: A URL to open instead of re-entering the agent. Mutually
        exclusive with ``prompt_template``.
