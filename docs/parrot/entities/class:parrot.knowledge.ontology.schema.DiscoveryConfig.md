---
type: Wiki Entity
title: DiscoveryConfig
id: class:parrot.knowledge.ontology.schema.DiscoveryConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for how relations are discovered in source data.
---

# DiscoveryConfig

Defined in [`parrot.knowledge.ontology.schema`](../summaries/mod:parrot.knowledge.ontology.schema.md).

```python
class DiscoveryConfig(BaseModel)
```

Configuration for how relations are discovered in source data.

Args:
    strategy: Overall discovery strategy.
    rules: List of discovery rules to apply.
