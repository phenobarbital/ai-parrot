---
id: F022
query_id: Q042
type: grep
intent: "R4: navigator-eventbus usage in integrations (Telegram bot process) and server."
executed_at: 2026-10-30T12:24:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-023]
---

# F022 — navigator_eventbus is imported in server/autonomous (orchestrator EventBus, evb, webhooks, filesystem hook) and integrations/matrix hook; core has lifecycle registry + observability fan-out; NO usage in the Telegram wrapper

## Summary

Grep in integrations+server src: hits only in `integrations/matrix/hook.py` (BaseHook/HookRegistry), `server/autonomous/{evb,webhooks,orchestrator,transport/filesystem/hook}.py` (`EventBus(...)` constructed in `orchestrator.py:240`). In core, 20 files import navigator_eventbus-derived lifecycle machinery under `parrot/core/events/`, plus `observability/fanout.py` (FC-024) and `roost/carriers/bus.py`. Zero hits under `integrations/telegram/`, `integrations/msteams/`, `integrations/slack/`.

## Citations

- path: `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py`
  lines: 30,240
  symbol: `EventBus`
  excerpt: |
    from navigator_eventbus import EventBus, Event, EventPriority
    self.event_bus = EventBus(...)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/hook.py`
  lines: 23-24
  symbol: `MatrixHook`
  excerpt: |
    from navigator_eventbus.hooks.base import BaseHook, HookRegistry
- path: `packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py`
  lines: 1
  symbol: `lifecycle registry`
  excerpt: |
    (navigator-eventbus backed lifecycle EventRegistry — 20 core files)

## Notes

Spike S4 answer: the Telegram bot process does NOT consume navigator-eventbus today; S-2 would add that wiring. The dependency itself is present and used elsewhere.
