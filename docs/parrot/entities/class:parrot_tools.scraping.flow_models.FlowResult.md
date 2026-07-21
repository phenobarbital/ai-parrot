---
type: Wiki Entity
title: FlowResult
id: class:parrot_tools.scraping.flow_models.FlowResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Aggregated result of a :class:`ScrapingFlow` execution.
---

# FlowResult

Defined in [`parrot_tools.scraping.flow_models`](../summaries/mod:parrot_tools.scraping.flow_models.md).

```python
class FlowResult(BaseModel)
```

Aggregated result of a :class:`ScrapingFlow` execution.

Attributes:
    flow_name: Name of the executed flow.
    node_results: Map of ``node_id -> result`` (typically a
        ``ScrapingResult`` dump).
    success: Whether the flow completed successfully.
    error_message: Failure detail when ``success`` is ``False``.
    elapsed_seconds: Total wall-clock execution time.
    nodes_completed: Number of nodes that completed.
    nodes_total: Total number of nodes in the flow.
    checkpoint_path: Path to the persisted checkpoint, if any.
    resumed_from: Node id the run resumed from, if applicable.
