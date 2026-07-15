---
type: Wiki Entity
title: HumanToolInput
id: class:parrot.human.tool.HumanToolInput
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Input schema for the HumanTool.
relates_to:
- concept: class:parrot.tools.abstract.AbstractToolArgsSchema
  rel: extends
---

# HumanToolInput

Defined in [`parrot.human.tool`](../summaries/mod:parrot.human.tool.md).

```python
class HumanToolInput(AbstractToolArgsSchema)
```

Input schema for the HumanTool.

The schema is a deliberate subset of :class:`HumanInteraction`:
consensus modes, escalation targets, and timeout actions are
intentionally NOT exposed to the LLM. Those are configuration
decisions that should be made at the agent/tool wiring layer,
not by the model on a per-invocation basis.
