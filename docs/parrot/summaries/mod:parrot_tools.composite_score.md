---
type: Wiki Summary
title: parrot_tools.composite_score
id: mod:parrot_tools.composite_score
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Composite Score Tool for Technical Analysis.
relates_to:
- concept: class:parrot_tools.composite_score.CompositeScoreInput
  rel: defines
- concept: class:parrot_tools.composite_score.CompositeScoreTool
  rel: defines
- concept: mod:parrot_tools.technical_analysis
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.composite_score`

Composite Score Tool for Technical Analysis.

Provides 0-10 bullish/bearish scores for ranking multiple assets by technical strength.

## Classes

- **`CompositeScoreInput(BaseModel)`** — Input schema for CompositeScoreTool.
- **`CompositeScoreTool(AbstractToolkit)`** — Tool for computing composite technical scores for asset ranking.
