---
type: Wiki Entity
title: StandaloneAgentLoader
id: class:parrot.cli.loaders.StandaloneAgentLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Load agents from the in-process AgentRegistry.
---

# StandaloneAgentLoader

Defined in [`parrot.cli.loaders`](../summaries/mod:parrot.cli.loaders.md).

```python
class StandaloneAgentLoader
```

Load agents from the in-process AgentRegistry.

Uses ``AgentRegistry.get_instance()`` with fuzzy name matching fallback
and an interactive ``questionary.select()`` picker when no name is given.

Attributes:
    logger: Module-level logger.

## Methods

- `async def load(self, name: str) -> AbstractBot` — Load a registered agent by name.
- `async def list_agents(self) -> List[BotMetadata]` — Return all registered agent metadata.
- `async def select_agent(self) -> str` — Present an interactive agent picker using questionary.
