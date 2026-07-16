---
type: Concept
title: create_action()
id: func:parrot.bots.flows.flow.actions.create_action
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create an action instance from a configuration.
---

# create_action

```python
def create_action(config: ActionDefinition) -> BaseAction
```

Create an action instance from a configuration.

Args:
    config: Action definition (Pydantic model)

Returns:
    Instantiated action ready to execute

Raises:
    ValueError: If action type is not registered
