---
type: Wiki Entity
title: StartSelectionTool
id: class:parrot.advisors.tools.start.StartSelectionTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Initiates a new product selection wizard session.
relates_to:
- concept: class:parrot.advisors.tools.base.BaseAdvisorTool
  rel: extends
---

# StartSelectionTool

Defined in [`parrot.advisors.tools.start`](../summaries/mod:parrot.advisors.tools.start.md).

```python
class StartSelectionTool(BaseAdvisorTool)
```

Initiates a new product selection wizard session.

This tool:
1. Loads all products from the catalog (optionally filtered by category)
2. Creates a new selection state in Redis
3. Returns the first question to ask the user

Use this when the user says things like:
- "Help me choose a product"
- "I need help finding the right shed"
- "What product would you recommend?"
- "I'm looking for..."
- "Start over"
- "Restart"
- "Clear session"
