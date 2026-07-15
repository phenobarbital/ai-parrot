---
type: Wiki Entity
title: RenderError
id: class:parrot.knowledge.ontology.tool_dispatcher.RenderError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when Jinja2 template rendering fails (e.g., ``StrictUndefined``).
---

# RenderError

Defined in [`parrot.knowledge.ontology.tool_dispatcher`](../summaries/mod:parrot.knowledge.ontology.tool_dispatcher.md).

```python
class RenderError(Exception)
```

Raised when Jinja2 template rendering fails (e.g., ``StrictUndefined``).

Attributes:
    field: The parameter field whose template triggered the error.
    message: The original ``UndefinedError`` or rendering message.
