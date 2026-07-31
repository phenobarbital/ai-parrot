---
type: Wiki Entity
title: ApplyCriteriaTool
id: class:parrot.advisors.tools.criteria.ApplyCriteriaTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Applies the user's answer to filter products and update selection state.
relates_to:
- concept: class:parrot.advisors.tools.base.BaseAdvisorTool
  rel: extends
---

# ApplyCriteriaTool

Defined in [`parrot.advisors.tools.criteria`](../summaries/mod:parrot.advisors.tools.criteria.md).

```python
class ApplyCriteriaTool(BaseAdvisorTool)
```

Applies the user's answer to filter products and update selection state.

This tool:
1. Parses the user's response to extract criteria
2. Filters products based on the criteria
3. Updates the selection state with new criteria
4. Creates a Memento snapshot for undo capability

Use this after the user answers a question to narrow down products.
