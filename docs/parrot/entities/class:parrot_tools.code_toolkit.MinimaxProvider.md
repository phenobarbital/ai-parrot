---
type: Wiki Entity
title: MinimaxProvider
id: class:parrot_tools.code_toolkit.MinimaxProvider
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Coding provider backed by Nvidia-hosted Minimax-compatible models.
---

# MinimaxProvider

Defined in [`parrot_tools.code_toolkit`](../summaries/mod:parrot_tools.code_toolkit.md).

```python
class MinimaxProvider
```

Coding provider backed by Nvidia-hosted Minimax-compatible models.

## Methods

- `async def run_task(self, task: CodingTask, model: str | None=None) -> CodingTaskResult` — Ask the Nvidia client to produce a structured coding plan/result.
- `def build_prompt(self, task: CodingTask, spec: str) -> str` — Build a structured-output prompt for Minimax-compatible models.
