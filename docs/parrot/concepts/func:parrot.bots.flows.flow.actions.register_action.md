---
type: Concept
title: register_action()
id: func:parrot.bots.flows.flow.actions.register_action
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Decorator to register an action class in the ACTION_REGISTRY.
---

# register_action

```python
def register_action(action_type: str)
```

Decorator to register an action class in the ACTION_REGISTRY.

Args:
    action_type: The string identifier for this action (e.g., "log", "webhook")

Example:
    >>> @register_action("custom")
    ... class CustomAction(BaseAction):
    ...     async def __call__(self, node_name, payload, **ctx):
    ...         print(f"Custom action on {node_name}")
