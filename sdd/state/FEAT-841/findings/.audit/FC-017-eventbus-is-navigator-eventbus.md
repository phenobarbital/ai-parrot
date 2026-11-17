---
id: FC-017
query_id: Q033
type: grep
intent: "Event bus publish/subscribe API available to SDD code (eventbus v2 / telemetry fan-out) — bus transport for work.completed."
executed_at: 2026-11-07T01:25:27Z
duration_ms: 1500
parent_id: null
depth: 0
---

# FC-017 — The only in-process event bus is the external navigator_eventbus package (FEAT-313/317); parrot.core.events no longer re-exports it; no SDD script publishes to any bus

## Summary

Grep for `def publish|def subscribe|class *EventBus|navigator_eventbus|from navigator.eventbus` across `parrot/` and the server package: every bus reference is an import of the external `navigator_eventbus` distribution (lifecycle events, hooks: `parrot/core/events/lifecycle/*`, `parrot/core/hooks/{sharepoint,messaging,matrix,jira_webhook,imap}.py`, `parrot/eval/runner.py`). `parrot/core/events/__init__.py` states the package "no longer re-exports `EventBus`/`Event`… import them directly from `navigator_eventbus`". The only `publish` method in-repo is `parrot/auth/oauth2/events.py:115` (OAuth connection events). No file under `parrot/sdd/` or `parrot/knowledge/wiki/ledger/` touches any bus — the SDD plane's only "bus" is the append-only ledger log (FC-006/FC-007). A `work.completed` event therefore has one realistic v1 transport (the ledger log) and one optional v2 transport (navigator_eventbus, process-local, requires a running server).

## Citations

- path: `packages/ai-parrot/src/parrot/core/events/__init__.py`
  lines: 6-10
  symbol: null
  excerpt: |
    FEAT-317). This package no longer re-exports ``EventBus``/``Event``/
    ``EventPriority``/``EventSubscription`` — import them directly from
    ``navigator_eventbus``::
        from navigator_eventbus import EventBus, Event, EventPriority, EventSubscription

- path: `packages/ai-parrot/src/parrot/core/events/lifecycle/yaml_loader.py`
  lines: 27-28
  symbol: null
  excerpt: |
    from navigator_eventbus.lifecycle.base import LifecycleEvent
    from navigator_eventbus.lifecycle.yaml_loader import (

- path: `packages/ai-parrot/src/parrot/core/hooks/matrix.py`
  lines: 26-27
  symbol: null
  excerpt: |
    from navigator_eventbus.hooks.base import BaseHook, HookRegistry
    from navigator_eventbus.hooks.models import HookType, MatrixHookConfig

- path: `packages/ai-parrot/src/parrot/eval/runner.py`
  lines: 32-32
  symbol: null
  excerpt: |
        from navigator_eventbus import EventBus

- path: `packages/ai-parrot/src/parrot/auth/oauth2/events.py`
  lines: 115-115
  symbol: `publish`
  excerpt: |
        async def publish(self, event: ConnectionEvent, state_payload: Optional[Dict[str, Any]] = 

## Notes

- 30 hits total, all imports of `navigator_eventbus.*`; none in `parrot/sdd`, `parrot/knowledge/wiki/ledger`, `parrot/flows/dev_loop`.
- [cross-lane: type=wiki_query, intent=navigator-eventbus brokers (Redis) availability for a cross-process subscriber — eventbus-brokers-port.spec.md]
