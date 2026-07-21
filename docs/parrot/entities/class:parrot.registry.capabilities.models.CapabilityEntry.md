---
type: Wiki Entity
title: CapabilityEntry
id: class:parrot.registry.capabilities.models.CapabilityEntry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A registered capability in the semantic index.
---

# CapabilityEntry

Defined in [`parrot.registry.capabilities.models`](../summaries/mod:parrot.registry.capabilities.models.md).

```python
class CapabilityEntry(BaseModel)
```

A registered capability in the semantic index.

Args:
    name: Unique name of the capability.
    description: Human-readable description used for embedding.
    resource_type: The type of resource this entry represents.
    embedding: Pre-computed embedding vector (None until build_index() is called).
    metadata: Arbitrary metadata dict for routing-specific information.
    not_for: Query patterns this capability should NOT match.
