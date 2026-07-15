---
type: Wiki Entity
title: AbstractToolArgsSchema
id: class:parrot.tools.abstract.AbstractToolArgsSchema
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base schema for tool arguments.
---

# AbstractToolArgsSchema

Defined in [`parrot.tools.abstract`](../summaries/mod:parrot.tools.abstract.md).

```python
class AbstractToolArgsSchema(BaseModel)
```

Base schema for tool arguments.

Subclasses can list field names in ``_context_fields`` that represent
runtime context injected by the framework (e.g. ``user_id``,
``session_id``).  These fields are **excluded** from the JSON schema
sent to the LLM so the model is never asked to provide them.  The
framework injects them before validation at execution time.
