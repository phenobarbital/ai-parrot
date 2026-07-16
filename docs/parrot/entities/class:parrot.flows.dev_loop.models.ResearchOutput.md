---
type: Wiki Entity
title: ResearchOutput
id: class:parrot.flows.dev_loop.models.ResearchOutput
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Structured output from the ``sdd-research`` dispatch.
---

# ResearchOutput

Defined in [`parrot.flows.dev_loop.models`](../summaries/mod:parrot.flows.dev_loop.models.md).

```python
class ResearchOutput(BaseModel)
```

Structured output from the ``sdd-research`` dispatch.

The research subagent creates the Jira ticket, the spec, the worktree
and (optionally) initial task artifacts, then emits this payload.

The model accepts a small set of common aliases under
``populate_by_name=True`` so subagent outputs that drift on field
names (``jira_key``, ``feature_id``, ``branch``, ``worktree``) still
validate. Pydantic's serialiser keeps the canonical names on
output.
