---
type: Wiki Entity
title: Trajectory
id: class:parrot.eval.models.Trajectory
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Full record of one agent attempt on a task.
---

# Trajectory

Defined in [`parrot.eval.models`](../summaries/mod:parrot.eval.models.md).

```python
class Trajectory(BaseModel)
```

Full record of one agent attempt on a task.

Retained raw in the report so old runs can be re-scored offline
without re-running the agent (spec D5).

Attributes:
    task_id: ID of the ``EvalTask`` this trajectory covers.
    attempt: Attempt index (1-based, up to ``k``).
    turns: Ordered list of conversational turns.
    final_output: Final agent response (text or structured output).
    final_state: Snapshot of world state captured after the rollout.
    tokens: Aggregated token usage.
    cost_usd: Estimated cost in US dollars.
    setup_latency_ms: Time to instantiate and bind the agent.
    latency_ms: Rollout-only wall-clock time.
    error: Exception string if the attempt failed, otherwise ``None``.
    trace_context: W3C traceparent/tracestate for distributed tracing.
