---
type: Wiki Entity
title: KBSelector
id: class:parrot.bots.kb.KBSelector
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Add KB selection capabilities to a bot.
---

# KBSelector

Defined in [`parrot.bots.kb`](../summaries/mod:parrot.bots.kb.md).

```python
class KBSelector
```

Add KB selection capabilities to a bot.

## Methods

- `async def select_kbs(self, question: str, available_kbs: List[Dict[str, str]]) -> KBOutput` — Select relevant KBs using LLM reasoning.
