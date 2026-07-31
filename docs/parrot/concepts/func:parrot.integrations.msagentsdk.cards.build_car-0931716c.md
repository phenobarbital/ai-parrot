---
type: Concept
title: build_card_attachment()
id: func:parrot.integrations.msagentsdk.cards.build_card_attachment
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wrap card JSON in the Bot Framework attachment envelope.
---

# build_card_attachment

```python
def build_card_attachment(card: dict) -> dict
```

Wrap card JSON in the Bot Framework attachment envelope.

Args:
    card: The Adaptive Card JSON dict (as returned by `render_card`).

Returns:
    The attachment envelope dict with `contentType`
    `"application/vnd.microsoft.card.adaptive"` and `content` set to
    `card`.
