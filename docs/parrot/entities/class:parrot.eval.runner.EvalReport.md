---
type: Wiki Entity
title: EvalReport
id: class:parrot.eval.runner.EvalReport
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Aggregated results of one evaluation run.
---

# EvalReport

Defined in [`parrot.eval.runner`](../summaries/mod:parrot.eval.runner.md).

```python
class EvalReport(BaseModel)
```

Aggregated results of one evaluation run.

Attributes:
    run_id: Unique identifier for this run (set by ``EvalRunner`` or
        the persistence sink).
    dataset_name: Name of the evaluated ``EvalDataset``.
    config: ``EvalRunConfig`` used for the run.
    pass_k: ``pass^k`` — fraction of tasks where ALL k attempts passed.
        This is the headline reliability metric.
    pass_at_1: ``pass@1`` — mean of (attempt-1 passed) across all tasks.
    results: All ``EvalResult`` objects (one per (task, attempt) pair).
    per_tag: Per-tag ``pass^k`` breakdown.
    p50_latency_ms: Median rollout latency across all attempts.
    p95_latency_ms: 95th-percentile rollout latency across all attempts.
    p50_setup_latency_ms: Median agent setup latency.
    p95_setup_latency_ms: 95th-percentile agent setup latency.
    p50_cost_usd: Median cost per attempt.
    p95_cost_usd: 95th-percentile cost per attempt.
    total_tasks: Total number of tasks in the dataset.
    total_attempts: Total number of (task, attempt) pairs executed.
    errors: Mapping of ``task_id`` → list of error messages.
