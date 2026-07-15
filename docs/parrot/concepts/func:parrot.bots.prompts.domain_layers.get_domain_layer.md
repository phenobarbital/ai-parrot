---
type: Concept
title: get_domain_layer()
id: func:parrot.bots.prompts.domain_layers.get_domain_layer
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Look up a registered domain layer by name.
---

# get_domain_layer

```python
def get_domain_layer(name: str) -> PromptLayer
```

Look up a registered domain layer by name.

Args:
    name: The domain layer name.

Returns:
    The registered PromptLayer.

Raises:
    KeyError: If the name is not registered.
