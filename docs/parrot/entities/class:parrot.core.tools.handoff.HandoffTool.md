---
type: Wiki Entity
title: HandoffTool
id: class:parrot.core.tools.handoff.HandoffTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tool for handing off task execution to a human user.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# HandoffTool

Defined in [`parrot.core.tools.handoff`](../summaries/mod:parrot.core.tools.handoff.md).

```python
class HandoffTool(AbstractTool)
```

Tool for handing off task execution to a human user.

.. deprecated::
    Prefer :class:`parrot.human.tool.HumanTool` with ``policy_id``
    for new code that requires tiered escalation.  ``HandoffTool``
    raises ``HumanInteractionInterrupt`` which requires the
    orchestrator to suspend the agent; ``HumanTool`` awaits the
    interaction directly and avoids the suspend/resume cycle
    entirely.

When an agent does not have enough information to complete a task,
it can call this tool with a prompt.  The tool attempts a short
bounded poll (5 × 100 ms) for an already-resolved result from the
manager.  If the result is available within the window, it is
returned immediately and the agent is never suspended.  If not, the
legacy ``HumanInteractionInterrupt`` is raised so the
orchestrator's existing suspend/resume path takes over.
