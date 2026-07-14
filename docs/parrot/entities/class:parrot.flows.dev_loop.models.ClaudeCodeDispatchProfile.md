---
type: Wiki Entity
title: ClaudeCodeDispatchProfile
id: class:parrot.flows.dev_loop.models.ClaudeCodeDispatchProfile
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Declarative profile consumed by ``ClaudeCodeDispatcher.dispatch()``.
---

# ClaudeCodeDispatchProfile

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class ClaudeCodeDispatchProfile(BaseModel)
```

Declarative profile consumed by ``ClaudeCodeDispatcher.dispatch()``.

``subagent`` selects a programmatic subagent from the ``agents=`` dict
passed to the SDK; when ``None``, ``system_prompt_override`` is used
and the dispatcher falls back to a generic session.
