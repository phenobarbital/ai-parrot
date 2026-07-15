---
type: Wiki Summary
title: parrot_tools.technical_analysis
id: mod:parrot_tools.technical_analysis
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Technical Analysis Tool
relates_to:
- concept: class:parrot_tools.technical_analysis.ADXOutput
  rel: defines
- concept: class:parrot_tools.technical_analysis.ATROutput
  rel: defines
- concept: class:parrot_tools.technical_analysis.CompositeScore
  rel: defines
- concept: class:parrot_tools.technical_analysis.TechnicalAnalysisInput
  rel: defines
- concept: class:parrot_tools.technical_analysis.TechnicalAnalysisTool
  rel: defines
- concept: class:parrot_tools.technical_analysis.TechnicalSignal
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot_tools
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.technical_analysis`

Technical Analysis Tool

## Classes

- **`TechnicalSignal`** — Structured technical signal with confidence scoring.
- **`ADXOutput(BaseModel)`** — ADX (Average Directional Index) indicator output.
- **`ATROutput(BaseModel)`** — ATR (Average True Range) indicator output with stop-loss levels.
- **`CompositeScore(BaseModel)`** — Composite technical score for asset ranking.
- **`TechnicalAnalysisInput(BaseModel)`**
- **`TechnicalAnalysisTool(AbstractToolkit)`** — Tool for performing Technical Analysis on stocks and crypto.
