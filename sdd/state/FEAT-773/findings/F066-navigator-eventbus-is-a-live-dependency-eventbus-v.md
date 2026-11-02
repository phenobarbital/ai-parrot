---
id: F066
query_id: Q013
type: wiki_page
intent: "Read finding: navigator-eventbus already wired in parrot (FEAT-747 F018) — bus availability for connection.* events."
executed_at: 2026-10-30T12:10:52Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FW-013]
---

# F066 — navigator-eventbus is a live dependency (EventBus v2 FEAT-310; FEAT-710 publish-only Streams fan-out with durable outbox; Roost bus carrier FEAT-747); no evidence the Telegram bot process subscribes to any bus topic today

## Summary

Reusing FEAT-747's verified finding: `observability/fanout.py` does `from navigator_eventbus import EventBus`, requires a Streams transport in publish-only mode (`_validate_bus`), keeps a durable outbox and forwards four usage lifecycle events with a redaction denylist; EventBus v2 provides `BusCore` (queued dispatch, retry, backpressure), DLQ, `HookManager.route_to_bus`; `parrot/roost/carriers/bus.py` is a navigator-eventbus carrier on a dedicated instance (FEAT-747 M9). Ledger `issue:9296682eda19` warned observability auto-boot was dead (memory says FEAT-725 fixed it). Nothing surfaced shows `ai-parrot-integrations` (Telegram/Slack/Teams wrappers) consuming bus events — the OAuth completion notifications are direct in-process calls from the callback (FW-011). So Spike S4's answer is "bus exists and publishes; integrations do not subscribe" pending codebase-lane grep.

## Citations

- path: `sdd/state/FEAT-747/findings/F018-eventbus-navigator.md`
  lines: n/a
  symbol: F018 digest (FEAT-310/710 facts)
  wiki_page_id: file:sdd/state/FEAT-747/findings/F018-eventbus-navigator.md
- path: `packages/ai-parrot/src/parrot/observability/fanout.py`
  lines: 1-45
  symbol: `setup_event_fanout`, `_validate_bus`, `redact_usage_event`, `FORWARDED_EVENTS`
  wiki_page_id: file:packages/ai-parrot/src/parrot/observability/fanout.py (score=0.48)
- path: `packages/ai-parrot/src/parrot/roost/carriers/bus.py`
  lines: n/a
  symbol: navigator-eventbus carrier (FEAT-747 M9)
  wiki_page_id: file:packages/ai-parrot/src/parrot/roost/carriers/bus.py (score=0.59)
- path: `docs/events/eventbus-migration.md`
  lines: n/a
  symbol: EventBus v2 Migration Notes (FEAT-310)
  wiki_page_id: file:docs/events/eventbus-migration.md (score=0.45)
- path: `sdd/tasks/completed/TASK-4553-event-fanout-wiring.md`
  lines: n/a
  symbol: `attach_bus` + `forward_to_bus` over durable Streams
  wiki_page_id: file:sdd/tasks/completed/TASK-4553-event-fanout-wiring.md (score=0.45)

## Notes

`[cross-lane: type=grep, intent=navigator_eventbus|EventBus imports under packages/ai-parrot-integrations/src and packages/ai-parrot-server/src to confirm zero subscribers in channel wrappers]`. Also relevant: `UserSocketManager` (`handlers/user.py`) already uses Redis PubSub for cross-process user delivery — a lighter alternative to the bus for web completion.
