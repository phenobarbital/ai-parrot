---
type: Wiki Entity
title: AgentLoadError
id: class:parrot.cli.loaders.AgentLoadError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when an agent cannot be loaded.
---

# AgentLoadError

Defined in [`parrot.cli.loaders`](../summaries/mod:parrot.cli.loaders.md).

```python
class AgentLoadError(Exception)
```

Raised when an agent cannot be loaded.

Attributes:
    agent_name: The name that was requested.
    suggestions: Fuzzy-matched agent names from the registry.
