---
type: Wiki Entity
title: ListEventsTool
id: class:parrot_tools.o365.events.ListEventsTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for listing events in the user's calendar.
relates_to:
- concept: class:parrot_tools.o365.base.O365Tool
  rel: extends
---

# ListEventsTool

Defined in [`parrot_tools.o365.events`](../summaries/mod:parrot_tools.o365.events.md).

```python
class ListEventsTool(O365Tool)
```

Tool for listing events in the user's calendar.

Uses OData query parameters ($top, $filter) for customization and
`Prefer: outlook.timezone` header to control response timezones.
