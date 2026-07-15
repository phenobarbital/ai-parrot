---
type: Wiki Entity
title: BudgetConfig
id: class:parrot.knowledge.graphindex.retriever.BudgetConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Token budget for Phase 4 result assembly.
---

# BudgetConfig

Defined in [`parrot.knowledge.graphindex.retriever`](../summaries/mod:parrot.knowledge.graphindex.retriever.md).

```python
class BudgetConfig(BaseModel)
```

Token budget for Phase 4 result assembly.

Args:
    max_tokens: Maximum total tokens to budget for the returned nodes.
    tokens_per_node_estimate: Rough heuristic for tokens consumed per
        node.  The actual count depends on content length; this is used
        only for truncation purposes.
