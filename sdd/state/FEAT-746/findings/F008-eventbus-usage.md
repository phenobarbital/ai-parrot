---
id: F008
query_id: [Q027, Q044]
type: grep
intent: "Eventbus: where navigator-eventbus (or any bus) is used; reply_to / correlation / dead-letter patterns."
executed_at: 2026-10-25T22:46:15Z
duration_ms: 0
parent_id: null
depth: 0
lane_origin: FC-010-eventbus-usage
---

# F008 — navigator-eventbus is used only as the in-process lifecycle-event registry (FEAT-313); no RPC-on-bus (reply_to / correlation_id / dead-letter) pattern in parrot

## Summary

All real imports of `navigator_eventbus` are in `parrot/core/events/`: the lifecycle layer re-exports `LifecycleEvent`, `TraceContext`, `EventRegistry`, `AsyncSubscriber`, `get_global_registry`, `scope`, `EventProvider`, `EventEmitterMixin`, `LoggingSubscriber`, `WebhookSubscriber` from `navigator_eventbus.lifecycle.*`, and `parrot/core/events/__init__.py` documents `from navigator_eventbus import EventBus, Event, EventPriority, EventSubscription`. Event classes under `core/events/lifecycle/events/{agent,client,flow,invoke,memory,message,tool}.py` subclass `LifecycleEvent`; `subscribers/opentelemetry.py` bridges events to OTel. A 40-file list matched the broad pattern (`eventbus|EventBus|reply_to|correlation_id|dead.letter`) but the hits outside `core/events` are webhook hooks (`core/hooks/*`), the autonomous transport (`autonomous/transport/base.py`, `autonomous/webhooks.py`) and telemetry — none implement request/reply over a bus. The read of a bus publish module (Q044) was skipped on budget; a `TraceContext` type already exists for correlation across events.

## Citations

- path: `packages/ai-parrot/src/parrot/core/events/__init__.py`
  lines: 8-10
  symbol: eventbus re-export docstring
  excerpt: |
    navigator_eventbus::
        from navigator_eventbus import EventBus, Event, EventPriority, EventSubscription
- path: `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py`
  lines: 18-24
  symbol: lifecycle re-exports
  excerpt: |
    from navigator_eventbus.lifecycle.trace import TraceContext
    from navigator_eventbus.lifecycle.base import LifecycleEvent
    from navigator_eventbus.lifecycle.registry import EventRegistry, AsyncSubscriber
    from navigator_eventbus.lifecycle.global_registry import get_global_registry, scope
    from navigator_eventbus.lifecycle.provider import EventProvider
    from navigator_eventbus.lifecycle.mixin import EventEmitterMixin, set_bootstrap_hook
- path: `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py`
  lines: 54-56
  symbol: subscribers re-exports
  excerpt: |
    from navigator_eventbus.lifecycle.subscribers.logging import LoggingSubscriber
    from navigator_eventbus.lifecycle.subscribers.webhook import WebhookSubscriber
- path: `packages/ai-parrot/src/parrot/core/events/lifecycle/events/tool.py`
  lines: 1
  symbol: tool lifecycle events (matched)
- path: `packages/ai-parrot/src/parrot/core/events/lifecycle/subscribers/opentelemetry.py`
  lines: 22-36
  symbol: OTel subscriber imports
  excerpt: |
    from navigator_eventbus.lifecycle.base import LifecycleEvent
        from navigator_eventbus.lifecycle.registry import EventRegistry
- path: `packages/ai-parrot/src/parrot/core/events/lifecycle/legacy_bridge.py`
  lines: 23
  symbol: `EventRegistry` import
- path: `packages/ai-parrot-server/src/parrot/autonomous/transport/base.py`
  lines: 1
  symbol: autonomous transport (matched broad pattern)
- path: `packages/ai-parrot/src/parrot/observability/fanout.py`
  lines: 24
  symbol: `ensure_shared_cost_calculator` import (matched)

## Notes

Q044 (read of a bus publish module) skipped: files_read budget exhausted. The FEAT-310/317 gRPC *ingress adapter* lives in navigator-eventbus itself (FC-002), so S6 (envelope on the bus) depends on navigator-eventbus capabilities outside this repo. [cross-lane: type=wiki_query, intent="navigator eventbus gRPC ingress adapter FEAT-310" to recover what the adapter does]
