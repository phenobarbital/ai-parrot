---
type: Concept
title: mention_from_card()
id: func:parrot.integrations.telegram.crew.mention.mention_from_card
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Build an @mention string from an AgentCard.
---

# mention_from_card

```python
def mention_from_card(card: AgentCard) -> str
```

Build an @mention string from an AgentCard.

Args:
    card: The AgentCard to extract the username from.

Returns:
    String in the format ``@username``.
