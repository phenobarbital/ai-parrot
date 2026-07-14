---
type: Wiki Entity
title: UndoSelectionTool
id: class:parrot.advisors.tools.undo.UndoSelectionTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Reverts the product selection to a previous state.
relates_to:
- concept: class:parrot.advisors.tools.base.BaseAdvisorTool
  rel: extends
---

# UndoSelectionTool

Defined in [`parrot.advisors.tools.undo`](../summaries/mod:parrot.advisors.tools.undo.md).

```python
class UndoSelectionTool(BaseAdvisorTool)
```

Reverts the product selection to a previous state.

Uses the Memento pattern to restore:
- Previous criteria
- Previous candidate products
- Previous questions asked

Use this when the user wants to:
- Go back and change an answer
- Undo their last choice
- Start over from a previous point
