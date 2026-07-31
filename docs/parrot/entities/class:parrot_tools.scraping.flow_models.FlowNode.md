---
type: Wiki Entity
title: FlowNode
id: class:parrot_tools.scraping.flow_models.FlowNode
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single stage in a :class:`ScrapingFlow` DAG.
---

# FlowNode

Defined in [`parrot_tools.scraping.flow_models`](../summaries/mod:parrot_tools.scraping.flow_models.md).

```python
class FlowNode(BaseModel)
```

A single stage in a :class:`ScrapingFlow` DAG.

Attributes:
    id: Unique node identifier within the flow.
    plan_ref: TemplatePlan name or plan fingerprint to execute.
    inputs: Map of ``param -> "node_id.field"`` data-dependency edges.
    session: Session label; nodes sharing a label share a BrowserContext.
    on_error: Failure policy — ``abort``, ``skip``, or ``retry``.
    max_retries: Retry budget used only when ``on_error == "retry"``.
