---
type: Wiki Entity
title: SuspendingWebHumanTool
id: class:parrot.handlers.web_hitl.SuspendingWebHumanTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: WebHumanTool variant wired for stateless REST suspend/resume (FEAT-204).
relates_to:
- concept: class:parrot.handlers.web_hitl.WebHumanTool
  rel: extends
---

# SuspendingWebHumanTool

Defined in [`parrot.handlers.web_hitl`](../summaries/mod:parrot.handlers.web_hitl.md).

```python
class SuspendingWebHumanTool(WebHumanTool)
```

WebHumanTool variant wired for stateless REST suspend/resume (FEAT-204).

Sets ``wait_strategy=WaitStrategy.SUSPEND``, which causes
:meth:`~parrot.human.tool.HumanTool._execute` to call
:meth:`~parrot.human.manager.HumanInteractionManager.request_human_input_async`
and raise :class:`~parrot.core.exceptions.HumanInteractionInterrupt` instead of
blocking.  The HTTP handler catches the interrupt, serialises the tool-loop
state, and returns a ``paused`` envelope so the frontend can drive the
resume flow via a later ``hitl_response``-tagged request.

Lazy manager resolution and ``current_web_session``-based target resolution
are fully inherited from :class:`WebHumanTool` — no re-implementation.

Both :class:`WebHumanTool` (WebSocket long-poll, FEAT-146) and this class
coexist.  Wire an agent with one or the other at construction:

* Blocking (WebSocket): ``ask_human = WebHumanTool(source_agent=name)``
* Stateless (REST):     ``ask_human = SuspendingWebHumanTool(source_agent=name)``

Args:
    default_targets: Fallback list of target human IDs.
    source_agent: Name of the agent that owns this tool.
    **kwargs: Forwarded to :class:`WebHumanTool`.
