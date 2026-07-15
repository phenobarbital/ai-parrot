---
type: Wiki Entity
title: ThinkInput
id: class:parrot_tools.think.ThinkInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input schema for the ThinkTool.
relates_to:
- concept: class:parrot.tools.abstract.AbstractToolArgsSchema
  rel: extends
---

# ThinkInput

Defined in [`parrot_tools.think`](../summaries/mod:parrot_tools.think.md).

```python
class ThinkInput(AbstractToolArgsSchema)
```

Input schema for the ThinkTool.

The thoughts field captures the agent's reasoning process, including:
- Problem analysis and clarification
- Assumptions being made
- Planned approach or strategy
- Potential issues or edge cases to consider

Note: A 'next_step' field was intentionally omitted as it tends to
cause hallucinations and rigid behavior in practice.
