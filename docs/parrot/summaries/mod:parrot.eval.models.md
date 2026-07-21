---
type: Wiki Summary
title: parrot.eval.models
id: mod:parrot.eval.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic v2 data models for the Generic Agent Evaluation Harness.
relates_to:
- concept: class:parrot.eval.models.EvalDataset
  rel: defines
- concept: class:parrot.eval.models.EvalResult
  rel: defines
- concept: class:parrot.eval.models.EvalTask
  rel: defines
- concept: class:parrot.eval.models.MetricScore
  rel: defines
- concept: class:parrot.eval.models.TokenUsage
  rel: defines
- concept: class:parrot.eval.models.ToolCallRecord
  rel: defines
- concept: class:parrot.eval.models.Trajectory
  rel: defines
- concept: class:parrot.eval.models.TurnRecord
  rel: defines
- concept: mod:parrot.eval.sandbox.base
  rel: references
---

# `parrot.eval.models`

Pydantic v2 data models for the Generic Agent Evaluation Harness.

FEAT-217 — All evaluation data contracts live here.  No behavior — pure data.
``SandboxSpec`` is defined in ``parrot.eval.sandbox.base`` and referenced
via a forward reference in ``EvalTask``; call ``EvalTask.model_rebuild()``
once ``SandboxSpec`` is importable (done in ``parrot/eval/__init__.py``).

## Classes

- **`EvalTask(BaseModel)`** — A single evaluation task (input + ground-truth expectation).
- **`ToolCallRecord(BaseModel)`** — Record of a single tool invocation during a trajectory turn.
- **`TurnRecord(BaseModel)`** — A single conversational turn in a trajectory.
- **`TokenUsage(BaseModel)`** — Aggregated token counts for a trajectory attempt.
- **`Trajectory(BaseModel)`** — Full record of one agent attempt on a task.
- **`MetricScore(BaseModel)`** — Score for a single metric on one attempt.
- **`EvalResult(BaseModel)`** — Evaluation outcome for a single (task, attempt) pair.
- **`EvalDataset(BaseModel)`** — A named collection of evaluation tasks.
