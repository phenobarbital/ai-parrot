---
type: Wiki Entity
title: CardRenderer
id: class:parrot.outputs.formats.card.CardRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renderer for metric cards with comparison data.
relates_to:
- concept: class:parrot.outputs.formats.base.BaseRenderer
  rel: extends
---

# CardRenderer

Defined in [`parrot.outputs.formats.card`](../summaries/mod:parrot.outputs.formats.card.md).

```python
class CardRenderer(BaseRenderer)
```

Renderer for metric cards with comparison data.
Extends BaseRenderer to display metrics in styled HTML cards.

## Methods

- `async def render(self, response: Any, environment: str='html', **kwargs) -> Tuple[str, str]` — Render card(s) as HTML.
