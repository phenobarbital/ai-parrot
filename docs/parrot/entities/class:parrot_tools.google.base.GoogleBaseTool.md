---
type: Wiki Entity
title: GoogleBaseTool
id: class:parrot_tools.google.base.GoogleBaseTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for Google Workspace tools leveraging :class:`GoogleClient`.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# GoogleBaseTool

Defined in [`parrot_tools.google.base`](../summaries/mod:parrot_tools.google.base.md).

```python
class GoogleBaseTool(AbstractTool)
```

Base class for Google Workspace tools leveraging :class:`GoogleClient`.

## Methods

- `def clear_client_cache(self) -> None` — Clear cached client instances.
