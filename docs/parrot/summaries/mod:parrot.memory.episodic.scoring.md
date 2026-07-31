---
type: Wiki Summary
title: parrot.memory.episodic.scoring
id: mod:parrot.memory.episodic.scoring
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pluggable importance scoring strategies for episodic memory.
relates_to:
- concept: class:parrot.memory.episodic.scoring.HeuristicScorer
  rel: defines
- concept: class:parrot.memory.episodic.scoring.ImportanceScorer
  rel: defines
- concept: class:parrot.memory.episodic.scoring.ValueScorer
  rel: defines
- concept: mod:parrot.memory.episodic.models
  rel: references
---

# `parrot.memory.episodic.scoring`

Pluggable importance scoring strategies for episodic memory.

Defines the ImportanceScorer protocol and provides two implementations:
- HeuristicScorer: normalized version of the original inline logic in store.py
- ValueScorer: port of AgentCoreMemory's ValueScorer, adapted for EpisodicMemory

## Classes

- **`ImportanceScorer(Protocol)`** — Protocol for pluggable importance scoring strategies.
- **`HeuristicScorer`** — Heuristic importance scorer based on outcome and error type.
- **`ValueScorer(BaseModel)`** — Heuristic interaction value scorer ported from AgentCoreMemory.
