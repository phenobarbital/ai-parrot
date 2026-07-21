---
type: Wiki Entity
title: UpdateEventTool
id: class:parrot_tools.o365.events.UpdateEventTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for updating an existing calendar event in Office365.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# UpdateEventTool

Defined in [`parrot_tools.o365.events`](../summaries/mod:parrot_tools.o365.events.md).

```python
class UpdateEventTool(O365Tool)
```

Tool for updating an existing calendar event in Office365.

The update uses a PATCH operation, so only fields provided will be updated.
