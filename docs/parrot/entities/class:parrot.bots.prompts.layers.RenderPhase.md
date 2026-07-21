---
type: Wiki Entity
title: RenderPhase
id: class:parrot.bots.prompts.layers.RenderPhase
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: When a layer's variables get resolved.
---

# RenderPhase

Defined in [`parrot.bots.prompts.layers`](../summaries/mod:parrot.bots.prompts.layers.md).

```python
class RenderPhase(str, Enum)
```

When a layer's variables get resolved.

CONFIGURE: Resolved once during configure(). Static variables like
           name, role, goal, backstory, rationale that don't change
           per request. The resolved text is cached and reused.

REQUEST:   Resolved on every ask()/ask_stream() call. Dynamic variables
           like context, user_context, chat_history that change per
           request.
