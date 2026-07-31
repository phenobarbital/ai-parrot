---
type: Wiki Entity
title: AgentConfig
id: class:parrot.setup.wizard.AgentConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Collected configuration for agent scaffolding.
---

# AgentConfig

Defined in [`parrot.setup.wizard`](../summaries/mod:parrot.setup.wizard.md).

```python
class AgentConfig
```

Collected configuration for agent scaffolding.

Attributes:
    name: Human-readable agent name (e.g. ``"My Research Agent"``).
    agent_id: URL-safe hyphenated slug derived from ``name``
        (e.g. ``"my-research-agent"``).
    provider_config: The LLM provider configuration for this agent.
    file_path: Absolute path where the generated agent ``.py`` file
        will be written.
