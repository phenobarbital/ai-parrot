---
type: Wiki Entity
title: ComponentDefinition
id: class:parrot.outputs.a2ui.catalog.base.ComponentDefinition
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Metadata describing a registered catalog component (spec §2 Data Models).
---

# ComponentDefinition

Defined in [`parrot.outputs.a2ui.catalog.base`](../summaries/mod:parrot.outputs.a2ui.catalog.base.md).

```python
class ComponentDefinition(BaseModel)
```

Metadata describing a registered catalog component (spec §2 Data Models).

Attributes:
    name: Component type name (e.g. ``"Infographic"``).
    catalog_id: Owning catalog id; defaults to the Parrot custom catalog.
    schema_: JSON-Schema for the component payload (wire/dump alias ``schema``).
    instructions: Embedded LLM guidance for producing this component (A2UI spec).
    requires_actions: Whether the component is action-bearing (D10b gate).
