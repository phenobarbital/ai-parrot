---
type: Wiki Summary
title: parrot.core.events.lifecycle.events.flow
id: mod:parrot.core.events.lifecycle.events.flow
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Flow / node orchestration lifecycle events.
relates_to:
- concept: class:parrot.core.events.lifecycle.events.flow.FlowCompletedEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.flow.FlowStartedEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.flow.NodeCompletedEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.flow.NodeFailedEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.flow.NodeSkippedEvent
  rel: defines
- concept: class:parrot.core.events.lifecycle.events.flow.NodeStartedEvent
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
---

# `parrot.core.events.lifecycle.events.flow`

Flow / node orchestration lifecycle events.

FEAT-176 Phase 1.5 — flow-layer events deferred by the Phase 1 spec
("Crew / multi-agent events").

Covers the ``AgentsFlow`` scheduler lifecycle: a run-level bracket
(``FlowStartedEvent`` / ``FlowCompletedEvent``) plus one event per node
dispatch outcome (started / completed / failed / skipped — the skipped
outcome exists only in the explicit-edge OR-join mode).

Emission site: :class:`parrot.bots.flows.flow.telemetry.FlowLifecycleAdapter`
attached to ``AgentsFlow``'s node-event listener channel. Events carry the
run's :class:`TraceContext` (root span for flow events, one child span per
node) so flow spans stitch with the client/tool spans emitted inside nodes.

## Classes

- **`FlowStartedEvent(LifecycleEvent)`** — Emitted when ``AgentsFlow.run_flow()`` begins dispatching.
- **`FlowCompletedEvent(LifecycleEvent)`** — Emitted after the scheduler loop ends and the result is aggregated.
- **`NodeStartedEvent(LifecycleEvent)`** — Emitted when the scheduler dispatches a node.
- **`NodeCompletedEvent(LifecycleEvent)`** — Emitted when a node's ``execute()`` returns successfully.
- **`NodeFailedEvent(LifecycleEvent)`** — Emitted when a node fails after exhausting its retry budget.
- **`NodeSkippedEvent(LifecycleEvent)`** — Emitted when OR-join skip-propagation marks a node as never-run.
