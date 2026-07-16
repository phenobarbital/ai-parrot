---
type: Wiki Summary
title: parrot.eval.events
id: mod:parrot.eval.events
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Eval lifecycle events for the Generic Agent Evaluation Harness.
relates_to:
- concept: class:parrot.eval.events.EvalRolloutCompleted
  rel: defines
- concept: class:parrot.eval.events.EvalRolloutFailed
  rel: defines
- concept: class:parrot.eval.events.EvalRolloutStarted
  rel: defines
- concept: class:parrot.eval.events.EvalRunCompleted
  rel: defines
- concept: class:parrot.eval.events.EvalRunStarted
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
---

# `parrot.eval.events`

Eval lifecycle events for the Generic Agent Evaluation Harness.

FEAT-217 — Module 11.

These events extend the FEAT-176 ``LifecycleEvent`` taxonomy with a new
orchestration-layer scope.  They are read-only (observers cannot abort a
run) and follow the model-B error-isolation guarantee of ``EventRegistry``
(subscribers that raise do NOT propagate exceptions into the runner).

Events are emitted via ``EventRegistry.emit()``; dual-emit to ``EventBus``
is per-subscriber opt-in (``forward_to_bus=True`` in ``subscribe()``).

One eval run = one distributed trace.  ``TraceContext.new_root()`` is
created at run start; ``TraceContext.child()`` is used per rollout attempt.

## Classes

- **`EvalRunStarted(LifecycleEvent)`** — Emitted when ``EvalRunner.run()`` begins.
- **`EvalRolloutStarted(LifecycleEvent)`** — Emitted just before a (task, attempt) rollout begins.
- **`EvalRolloutCompleted(LifecycleEvent)`** — Emitted after a (task, attempt) rollout completes successfully.
- **`EvalRolloutFailed(LifecycleEvent)`** — Emitted when a (task, attempt) rollout raises an exception.
- **`EvalRunCompleted(LifecycleEvent)`** — Emitted when ``EvalRunner.run()`` finishes (whether or not all tasks
