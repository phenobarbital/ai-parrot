---
type: Wiki Entity
title: ToolNameCollisionError
id: class:parrot.tools.manager.ToolNameCollisionError
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Raised when two toolkits try to register the same tool name.
---

# ToolNameCollisionError

Defined in [`parrot.tools.manager`](../summaries/mod:parrot.tools.manager.md).

```python
class ToolNameCollisionError(ValueError)
```

Raised when two toolkits try to register the same tool name.

Only raised for tools originating from toolkits that opted into
namespacing via ``AbstractToolkit.tool_prefix``. Legacy (unprefixed)
tools fall back to the previous warn-and-skip behaviour to avoid
breaking untouched toolkits during the migration.
