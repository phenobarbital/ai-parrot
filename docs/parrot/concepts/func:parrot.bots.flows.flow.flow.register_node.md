---
type: Concept
title: register_node()
id: func:parrot.bots.flows.flow.flow.register_node
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Register a Node subclass under ``name`` in ``NODE_REGISTRY``.
---

# register_node

```python
def register_node(name: str) -> Callable[[Type[Node]], Type[Node]]
```

Register a Node subclass under ``name`` in ``NODE_REGISTRY``.

This is a decorator factory; apply it to a Node subclass:

Example::

    @register_node("my-type")
    class MyNode(AgentNode):
        ...

Args:
    name: The type key under which to register the class. Must be unique
        across the registry.

Returns:
    A decorator that registers the class and returns it unchanged.

Raises:
    ValueError: If ``name`` is already registered.
    TypeError: If the decorated class is not a ``Node`` subclass.
