---
type: Wiki Entity
title: WebHumanTool
id: class:parrot.handlers.web_hitl.WebHumanTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A :class:`~parrot.human.tool.HumanTool` that auto-resolves manager
relates_to:
- concept: class:parrot.human.tool.HumanTool
  rel: extends
---

# WebHumanTool

Defined in [`parrot.handlers.web_hitl`](../summaries/mod:parrot.handlers.web_hitl.md).

```python
class WebHumanTool(HumanTool)
```

A :class:`~parrot.human.tool.HumanTool` that auto-resolves manager
and target from the current web request context.

Resolution order for the manager:
    1. ``self.manager`` if non-``None`` (set externally).
    2. :func:`~parrot.human.get_default_human_manager` (set by bootstrap).

Resolution order for ``target_humans`` on each invocation:
    1. Explicit ``target_humans`` from the LLM call (``kwargs``).
    2. ``self.default_targets`` from construction.
    3. :func:`get_current_web_session` — the ContextVar set by
       :meth:`~parrot.handlers.agent.AgentTalk.post` at request entry.

Args:
    default_targets: Fallback list of target human IDs.
    source_agent: Name of the agent that owns this tool (used to identify
        the source in the wire payload).
    **kwargs: Forwarded to :class:`~parrot.human.tool.HumanTool`.
