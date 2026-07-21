---
type: Wiki Entity
title: BaseAdvisorTool
id: class:parrot.advisors.tools.base.BaseAdvisorTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Base class for Product Advisor tools.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# BaseAdvisorTool

Defined in [`parrot.advisors.tools.base`](../summaries/mod:parrot.advisors.tools.base.md).

```python
class BaseAdvisorTool(AbstractTool)
```

Base class for Product Advisor tools.

Provides common functionality:
- State manager access
- Catalog access
- Question set access
- Standardized error handling
