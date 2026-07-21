---
type: Wiki Entity
title: BasicNode
id: class:parrot.outputs.a2ui.catalog.base.BasicNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A node in a lowered A2UI *Basic Catalog* tree.
---

# BasicNode

Defined in [`parrot.outputs.a2ui.catalog.base`](../summaries/mod:parrot.outputs.a2ui.catalog.base.md).

```python
class BasicNode(BaseModel)
```

A node in a lowered A2UI *Basic Catalog* tree.

The output of a component's ``lower()`` is a nested tree of Basic Catalog
primitives (e.g. ``Column``, ``Row``, ``Text``, ``Image``). Unlike the wire
:class:`~parrot.outputs.a2ui.models.Component` (a flat adjacency list keyed by
id), a lowered tree nests its ``children`` directly — this is an internal,
render-facing representation, not a wire message.

Attributes:
    component: Basic Catalog component name.
    properties: Declarative properties for the primitive.
    children: Nested child nodes (fleshed out further in Module 3).
