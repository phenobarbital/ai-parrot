---
type: Wiki Entity
title: ParsedResponse
id: class:parrot.integrations.parser.ParsedResponse
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Structured response content extracted from AIMessage.
---

# ParsedResponse

Defined in [`parrot.integrations.parser`](../summaries/mod:parrot.integrations.parser.md).

```python
class ParsedResponse
```

Structured response content extracted from AIMessage.

## Methods

- `def has_attachments(self) -> bool` — Check if there are any file attachments.
- `def has_table(self) -> bool` — Check if there is table data to render.
- `def has_code(self) -> bool` — Check if there is code to render.
- `def has_charts(self) -> bool` — Check if there are charts to render.
