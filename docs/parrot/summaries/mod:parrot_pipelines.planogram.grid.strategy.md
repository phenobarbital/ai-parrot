---
type: Wiki Summary
title: parrot_pipelines.planogram.grid.strategy
id: mod:parrot_pipelines.planogram.grid.strategy
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract Grid Strategy and NoGrid default implementation.
relates_to:
- concept: class:parrot_pipelines.planogram.grid.strategy.AbstractGridStrategy
  rel: defines
- concept: class:parrot_pipelines.planogram.grid.strategy.NoGrid
  rel: defines
- concept: func:parrot_pipelines.planogram.grid.strategy.get_strategy
  rel: defines
- concept: mod:parrot_pipelines.planogram.grid.models
  rel: references
---

# `parrot_pipelines.planogram.grid.strategy`

Abstract Grid Strategy and NoGrid default implementation.

Defines the ABC that all grid decomposition strategies implement,
plus NoGrid which preserves the current single-image detection behavior.

## Classes

- **`AbstractGridStrategy(ABC)`** — Base class for grid decomposition strategies.
- **`NoGrid(AbstractGridStrategy)`** — Default grid strategy — no decomposition.

## Functions

- `def get_strategy(grid_type: GridType) -> AbstractGridStrategy` — Instantiate and return the grid strategy for the given GridType.
