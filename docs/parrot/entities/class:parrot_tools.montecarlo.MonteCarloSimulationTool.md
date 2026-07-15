---
type: Wiki Entity
title: MonteCarloSimulationTool
id: class:parrot_tools.montecarlo.MonteCarloSimulationTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Run Monte Carlo simulations to provide probability distributions of outcomes.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# MonteCarloSimulationTool

Defined in [`parrot_tools.montecarlo`](../summaries/mod:parrot_tools.montecarlo.md).

```python
class MonteCarloSimulationTool(AbstractTool)
```

Run Monte Carlo simulations to provide probability distributions of outcomes.

Answers questions like 'what is the range of possible EBITDA values if
kiosks vary between 800-1200?' with confidence intervals.
