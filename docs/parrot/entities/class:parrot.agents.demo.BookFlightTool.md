---
type: Wiki Entity
title: BookFlightTool
id: class:parrot.agents.demo.BookFlightTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Demo tool that books a flight — or raises an interrupt on invalid input.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# BookFlightTool

Defined in [`parrot.agents.demo`](../summaries/mod:parrot.agents.demo.md).

```python
class BookFlightTool(AbstractTool)
```

Demo tool that books a flight — or raises an interrupt on invalid input.

Accepts a *destination* and a *date*. If the date does not match
``YYYY-MM-DD``, raises :class:`~parrot.core.exceptions.HumanInteractionInterrupt`
so the agent can ask the user to provide a corrected date via the handoff
path. On a valid date, returns a fake booking confirmation string.

Attributes:
    name: Tool name as registered in the LLM function-calling schema.
