---
type: Wiki Entity
title: HumanTool
id: class:parrot.human.tool.HumanTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool that pauses agent execution to request human input.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# HumanTool

Defined in [`parrot.human.tool`](../summaries/mod:parrot.human.tool.md).

```python
class HumanTool(AbstractTool)
```

Tool that pauses agent execution to request human input.

The LLM invokes this tool when it needs information, approval,
or a decision from a human operator.  The tool blocks until the
human responds (or the configured timeout expires).

Args:
    manager: HumanInteractionManager instance.
    default_channel: Channel to dispatch interactions to. When ``None``
        the tool picks the first registered channel on the manager.
    default_targets: Default human IDs to send interactions to.
    source_agent: Name of the agent that owns this tool.
