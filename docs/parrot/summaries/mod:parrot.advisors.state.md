---
type: Wiki Summary
title: parrot.advisors.state
id: mod:parrot.advisors.state
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.advisors.state
relates_to:
- concept: class:parrot.advisors.state.SelectionHistory
  rel: defines
- concept: class:parrot.advisors.state.SelectionPhase
  rel: defines
- concept: class:parrot.advisors.state.SelectionState
  rel: defines
- concept: class:parrot.advisors.state.StateSnapshot
  rel: defines
---

# `parrot.advisors.state`

## Classes

- **`SelectionPhase(str, Enum)`** — Phases of the product selection wizard.
- **`SelectionState(BaseModel)`** — Current state of product selection.
- **`StateSnapshot`** — Memento: Immutable snapshot of SelectionState.
- **`SelectionHistory(BaseModel)`** — Memento Caretaker: Manages state history for undo/redo.
