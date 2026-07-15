---
type: Wiki Entity
title: LocalKBMixin
id: class:parrot.bots.stores.local.LocalKBMixin
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Mixin to add local markdown KB support to agents.
---

# LocalKBMixin

Defined in [`parrot.bots.stores.local`](../summaries/mod:parrot.bots.stores.local.md).

```python
class LocalKBMixin
```

Mixin to add local markdown KB support to agents.

Usage:
    class AbstractBot(DBInterface, LocalKBMixin, ABC):
        ...

This mixin provides:
- Automatic KB directory detection
- Loading of markdown files from AGENTS_DIR/<agent_name>/kb/
- Integration with the agent's knowledge_bases list
- Proper error handling and logging

## Methods

- `async def configure_local_kb(self) -> None` — Configure local markdown KB for this agent.
- `def has_local_kb(self) -> bool` — Check if agent has a local KB loaded.
- `def get_local_kb_info(self) -> Optional[dict]` — Get information about the loaded local KB.
