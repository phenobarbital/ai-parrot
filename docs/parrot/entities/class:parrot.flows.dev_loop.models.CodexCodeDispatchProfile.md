---
type: Wiki Entity
title: CodexCodeDispatchProfile
id: class:parrot.flows.dev_loop.models.CodexCodeDispatchProfile
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Declarative profile consumed by ``CodexCodeDispatcher.dispatch()``.
---

# CodexCodeDispatchProfile

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class CodexCodeDispatchProfile(BaseModel)
```

Declarative profile consumed by ``CodexCodeDispatcher.dispatch()``.

The v1 Codex integration is intentionally scoped to Development. The
profile still keeps ``subagent`` explicit so the dispatcher can load the
same SDD subagent prompt body used by the Claude Code path.
