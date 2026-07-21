---
type: Wiki Entity
title: ToolList
id: class:parrot.handlers.bots.ToolList
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: ToolList — returns all registered tools, PBAC-filtered when PDP configured.
---

# ToolList

Defined in [`parrot.handlers.bots`](../summaries/mod:parrot.handlers.bots.md).

```python
class ToolList(_PBACHandlerMixin, BaseView)
```

ToolList — returns all registered tools, PBAC-filtered when PDP configured.

When the PDP evaluator is available (``app['abac']`` is set), tools are
filtered using ``evaluator.filter_resources(..., ResourceType.TOOL, ...,
"tool:list")``. Returns all tools when PDP is absent (fail-open).

PBAC helpers (``_get_pbac_evaluator``, ``_build_eval_context``) are
inherited from ``_PBACHandlerMixin``.

## Methods

- `async def get(self)` — List all tools, filtered by PBAC ``tool:list`` action when PDP configured.
