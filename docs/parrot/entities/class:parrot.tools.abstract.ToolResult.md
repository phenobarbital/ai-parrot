---
type: Wiki Entity
title: ToolResult
id: class:parrot.tools.abstract.ToolResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Standardized tool result format.
---

# ToolResult

Defined in [`parrot.tools.abstract`](../summaries/mod:parrot.tools.abstract.md).

```python
class ToolResult(BaseModel)
```

Standardized tool result format.

## Methods

- `def spoken_content(self) -> str` — Returns content for voice synthesis.
- `def has_display_content(self) -> bool` — Check if there's visual content to display.
