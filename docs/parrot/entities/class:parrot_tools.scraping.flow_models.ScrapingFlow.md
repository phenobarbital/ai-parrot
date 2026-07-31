---
type: Wiki Entity
title: ScrapingFlow
id: class:parrot_tools.scraping.flow_models.ScrapingFlow
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: DAG of :class:`FlowNode`s with data-dependency edges and session affinity.
---

# ScrapingFlow

Defined in [`parrot_tools.scraping.flow_models`](../summaries/mod:parrot_tools.scraping.flow_models.md).

```python
class ScrapingFlow(BaseModel)
```

DAG of :class:`FlowNode`s with data-dependency edges and session affinity.

Attributes:
    name: Flow name.
    description: Human-readable description.
    nodes: The flow's nodes (declaration order is preserved as a stable
        tiebreaker for topological ordering).
    global_params: Parameters available to every node at execution time.

## Methods

- `def validate_dag(self) -> 'ScrapingFlow'` — Validate the DAG (unique ids, no dangling refs, no cycles) and
- `def topological_order(self) -> List[FlowNode]` — Return the flow's nodes in dependency (execution) order.
