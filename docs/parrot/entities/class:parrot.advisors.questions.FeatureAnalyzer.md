---
type: Wiki Entity
title: FeatureAnalyzer
id: class:parrot.advisors.questions.FeatureAnalyzer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Analyzes a product catalog to identify discriminating features.
---

# FeatureAnalyzer

Defined in [`parrot.advisors.questions`](../summaries/mod:parrot.advisors.questions.md).

```python
class FeatureAnalyzer
```

Analyzes a product catalog to identify discriminating features.

This runs BEFORE the LLM to provide structured input for question generation.

## Methods

- `def analyze(self) -> CatalogAnalysis` — Run complete catalog analysis.
