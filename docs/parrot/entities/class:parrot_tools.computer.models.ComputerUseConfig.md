---
type: Wiki Entity
title: ComputerUseConfig
id: class:parrot_tools.computer.models.ComputerUseConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for the ComputerUse tool type in GoogleGenAIClient.
---

# ComputerUseConfig

Defined in [`parrot_tools.computer.models`](../summaries/mod:parrot_tools.computer.models.md).

```python
class ComputerUseConfig(BaseModel)
```

Configuration for the ComputerUse tool type in GoogleGenAIClient.

Controls which environment the computer-use model operates in and
which predefined functions (actions) are excluded.

Attributes:
    environment: The environment string — always ENVIRONMENT_BROWSER
        for browser automation.
    excluded_actions: List of predefined function names to exclude
        from the model's available action set.
