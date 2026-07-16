---
type: Wiki Entity
title: GetCurrentStateTool
id: class:parrot.advisors.tools.state.GetCurrentStateTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Returns the current state of the product selection process.
relates_to:
- concept: class:parrot.advisors.tools.base.BaseAdvisorTool
  rel: extends
---

# GetCurrentStateTool

Defined in [`parrot.advisors.tools.state`](../summaries/mod:parrot.advisors.tools.state.md).

```python
class GetCurrentStateTool(BaseAdvisorTool)
```

Returns the current state of the product selection process.

Useful for:
- Debugging selection issues
- Showing progress to the user
- Resuming interrupted sessions
- Understanding why certain products were eliminated
