---
type: Wiki Summary
title: parrot.eval.runner
id: mod:parrot.eval.runner
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: EvalRunner + EvalReport for the Generic Agent Evaluation Harness.
relates_to:
- concept: class:parrot.eval.runner.EvalReport
  rel: defines
- concept: class:parrot.eval.runner.EvalRunConfig
  rel: defines
- concept: class:parrot.eval.runner.EvalRunner
  rel: defines
- concept: mod:parrot.core.events.evb
  rel: references
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
- concept: mod:parrot.core.events.lifecycle.trace
  rel: references
- concept: mod:parrot.eval.evaluators.base
  rel: references
- concept: mod:parrot.eval.events
  rel: references
- concept: mod:parrot.eval.models
  rel: references
- concept: mod:parrot.eval.rollout
  rel: references
- concept: mod:parrot.eval.sandbox.base
  rel: references
---

# `parrot.eval.runner`

EvalRunner + EvalReport for the Generic Agent Evaluation Harness.

FEAT-217 — Module 9.

``EvalRunner`` orchestrates the full evaluation loop:
  - Runs ``k`` attempts per task.
  - For each attempt: acquire sandbox → reset → bind agent → rollout →
    snapshot → evaluate → release.
  - Aggregates ``pass^k`` (all-k-pass fraction) and ``pass@1`` (attempt-1
    mean) plus per-tag breakdowns and latency/cost percentiles.
  - Retains raw ``Trajectory`` per attempt (spec D5).
  - Emits eval lifecycle events via ``EventBus`` when configured.
  - Persists the report via ``EvalReportSink`` when configured.

## Classes

- **`EvalRunConfig(BaseModel)`** — Configuration for a single evaluation run.
- **`EvalReport(BaseModel)`** — Aggregated results of one evaluation run.
- **`EvalRunner`** — Orchestrates an evaluation run across all tasks in a dataset.
