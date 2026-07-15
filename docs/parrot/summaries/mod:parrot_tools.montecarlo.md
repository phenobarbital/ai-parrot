---
type: Wiki Summary
title: parrot_tools.montecarlo
id: mod:parrot_tools.montecarlo
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MonteCarloSimulationTool — Stochastic simulation with distributions.
relates_to:
- concept: class:parrot_tools.montecarlo.MonteCarloInput
  rel: defines
- concept: class:parrot_tools.montecarlo.MonteCarloSimulationTool
  rel: defines
- concept: class:parrot_tools.montecarlo.VariableDistribution
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
- concept: mod:parrot_tools.whatif
  rel: references
---

# `parrot_tools.montecarlo`

MonteCarloSimulationTool — Stochastic simulation with distributions.

Runs N simulations to provide probability distributions of outcomes
instead of single-point estimates.

## Classes

- **`VariableDistribution(BaseModel)`** — Distribution specification for a variable.
- **`MonteCarloInput(BaseModel)`** — Input schema for MonteCarloSimulationTool.
- **`MonteCarloSimulationTool(AbstractTool)`** — Run Monte Carlo simulations to provide probability distributions of outcomes.
