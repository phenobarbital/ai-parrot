---
type: Wiki Summary
title: parrot.advisors.tools.undo
id: mod:parrot.advisors.tools.undo
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: UndoSelectionTool - Reverts to the previous selection state (Memento pattern).
relates_to:
- concept: class:parrot.advisors.tools.undo.RedoSelectionTool
  rel: defines
- concept: class:parrot.advisors.tools.undo.UndoSelectionArgs
  rel: defines
- concept: class:parrot.advisors.tools.undo.UndoSelectionTool
  rel: defines
- concept: mod:parrot.advisors.tools.base
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.advisors.tools.undo`

UndoSelectionTool - Reverts to the previous selection state (Memento pattern).

## Classes

- **`UndoSelectionArgs(ProductAdvisorToolArgs)`** — Arguments for undo operation.
- **`UndoSelectionTool(BaseAdvisorTool)`** — Reverts the product selection to a previous state.
- **`RedoSelectionTool(BaseAdvisorTool)`** — Re-applies a previously undone action.
