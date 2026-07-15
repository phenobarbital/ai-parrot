---
type: Wiki Summary
title: parrot.bots.flows.flow.telemetry
id: mod:parrot.bots.flows.flow.telemetry
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: FlowLifecycleAdapter — bridge AgentsFlow scheduler events to FEAT-176.
relates_to:
- concept: class:parrot.bots.flows.flow.telemetry.FlowLifecycleAdapter
  rel: defines
- concept: mod:parrot.core.events.lifecycle.base
  rel: references
- concept: mod:parrot.core.events.lifecycle.events.flow
  rel: references
- concept: mod:parrot.core.events.lifecycle.global_registry
  rel: references
- concept: mod:parrot.core.events.lifecycle.registry
  rel: references
- concept: mod:parrot.core.events.lifecycle.trace
  rel: references
---

# `parrot.bots.flows.flow.telemetry`

FlowLifecycleAdapter — bridge AgentsFlow scheduler events to FEAT-176.

FEAT-176 Phase 1.5. Translates the scheduler's node-event channel
(``AgentsFlow(on_node_event=...)`` / ``add_node_event_listener``) into
typed :class:`LifecycleEvent` instances emitted on an
:class:`EventRegistry` — by default the process-wide global registry, so
every already-registered subscriber (OpenTelemetry, logging, webhook,
usage recorders) observes flow/node spans with zero extra wiring.

Trace identity:

- The run's root :class:`TraceContext` lives on ``FlowContext.trace_context``
  (created lazily here when the caller didn't seed one). Flow-level events
  carry the root span.
- Each node gets ONE child span, shared by its started/completed/failed
  events, so OTel subscribers can reconstruct the span tree
  (flow → node → client/tool calls made inside the node, which can read
  ``ctx.trace_context`` to parent their own spans).

Usage::

    flow = AgentsFlow("my-flow")
    flow.add_node_event_listener(FlowLifecycleAdapter())

## Classes

- **`FlowLifecycleAdapter`** — Node-event listener that emits typed FEAT-176 lifecycle events.
