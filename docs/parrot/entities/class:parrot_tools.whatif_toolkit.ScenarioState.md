---
type: Wiki Entity
title: ScenarioState
id: class:parrot_tools.whatif_toolkit.ScenarioState
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Internal state for a scenario being built incrementally.
---

# ScenarioState

Defined in [`parrot_tools.whatif_toolkit`](../summaries/mod:parrot_tools.whatif_toolkit.md).

```python
class ScenarioState
```

Internal state for a scenario being built incrementally.

## Methods

- `def is_ready(self) -> bool` — Scenario has at least one action defined.
- `def is_solved(self) -> bool` — Scenario has been simulated.
