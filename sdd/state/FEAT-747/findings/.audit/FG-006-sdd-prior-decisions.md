---
id: FG-006
query_id: Q055
type: git_log
intent: "Find SDD specs/proposals already covering matrix, eventbus, audit ledger, registry — prior decisions to respect."
executed_at: 2026-10-25T22:42:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# FG-006 — Prior SDD decisions: FEAT-463/464 Matrix swarm, FEAT-710/711 eventbus fan-out, WorkingMemory task memory, FEAT-575/425 crew, FEAT-436 registry drift

## Summary

~60 SDD-doc commits matched in 365 days. Directly relevant prior decisions: (1) **FEAT-463 matrix-agents-swarm** + **FEAT-464 matrix-swarm-sample** (approved 2026-08-26) — see FG-003. (2) **FEAT-710 parrot-telemetry-event-fanout** (approved 2026-10-20, rev 0.4 on 10-21) — chooses *navigator-eventbus* `EventBus(transport="streams", publish_only=True, outbox=<sqlite>)` with at-least-once delivery, dedup by envelope `event_id`, a *dedicated* bus instance (never the autonomous orchestrator's bus), `EventRegistry.attach_bus()` + serializer hook delivered upstream as **FEAT-711** in `../navigator-eventbus`; the server's `autonomous/orchestrator.py:245` already constructs an `EventBus`. (3) **workingmemory-toolkit proposal** (2026-09-08) — see FG-004. (4) Crew specs FEAT-575 (handler default key), FEAT-425 agentcrew-tales-research; (5) FEAT-436 sync-tool-registry-drift, FEAT-427 (TOOL_REGISTRY generation). No SDD document covers a performative layer, an inter-agent grant, or a shared blackboard. No match for "audit ledger"/"AuditLedger" in SDD doc commit messages.

## Citations

- sha: `0aca76bebe` date: 2026-10-21 author: Jesus — sdd: FEAT-710 spec rev 0.4 — Q2 dedicated EventBus instance — files: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
- sha: `fbbb213eaa` date: 2026-10-20 author: Jesus — sdd: FEAT-710 spec rev 0.3 — native forward_to_bus over navigator-eventbus FEAT-711
- sha: `d5362e68cb` date: 2026-08-26 author: Jesus — sdd: approve spec for FEAT-464 — matrix-swarm-sample — files: `sdd/specs/matrix-swarm-sample.spec.md`
- sha: `ad13833b6b` date: 2026-08-26 author: Jesus Lara — sdd: add spec for FEAT-463 — matrix-agents-swarm — files: `sdd/specs/matrix-agents-swarm.spec.md`
- sha: `88f35dfa56` date: 2026-08-26 author: Jesus Lara — sdd: resolve all open questions for matrix-agents-swarm brainstorm — files: `sdd/proposals/matrix-agents-swarm.brainstorm.md`
- sha: `4f066afcbd` date: 2026-09-08 author: Jesus Lara — working memory optimized for agents — files: `sdd/proposals/workingmemory-toolkit.proposal.md`
- sha: `cb645df2ae` date: 2026-09-18 author: Jesus Lara — sdd: add spec for FEAT-575 — agentcrew-handler-default-key
- sha: `384426f115` date: 2026-08-17 author: Jesus — sdd: add spec for FEAT-425 — agentcrew-tales-research
- sha: `109b9011e8` date: 2026-08-20 author: Jesus — sdd: add spec for FEAT-436 — sync-tool-registry-drift
- path: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
  lines: 80-112
  symbol: `Overview`
  excerpt: |
    global EventRegistry ──▶ attach_bus(bus, serializer=redact_usage_event)  (navigator-eventbus FEAT-711)
    EventBus(transport="streams", publish_only=True, outbox=<per-worker SQLite path>)
      outbox write-ahead → XADD → ack ; relay re-publishes after failure/restart (at-least-once)
    Redis Streams consumer group ──▶ external consumer — dedups by envelope event_id
- path: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
  lines: 259-292
  symbol: `setup_event_fanout`
  excerpt: |
    EventBus(redis_url=..., transport="streams", publish_only=True, channel_prefix="parrot:events:", outbox=f"{dir}/{hostname}-{pid}.db")
    "This is a dedicated instance, never the autonomous orchestrator's bus (§8 Q2)."
    def setup_event_fanout(bus: Optional[EventBus] = None) -> None  # observability/fanout.py (new)
- path: `sdd/specs/parrot-telemetry-event-fanout.spec.md`
  lines: 404-431
  symbol: `EventRegistry`
  excerpt: |
    from parrot.core.events.lifecycle import get_global_registry   # observability/bootstrap.py:134-138
    from navigator_eventbus.lifecycle.registry import EventRegistry
    class EventRegistry: subscribe(event_type, callback, ..., forward_to_bus: bool = False) -> str   # :121-127
    `EventBus` import: as used at ai-parrot-server/src/parrot/autonomous/orchestrator.py:245
- path: `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py`
  lines: 245
  symbol: `EventBus`
  excerpt: |
    (per FEAT-710 contract: the one place an EventBus is constructed in ai-parrot today)
- path: `packages/ai-parrot/src/parrot/core/events/lifecycle/`
  symbol: `get_global_registry`
- path: `sdd/specs/matrix-agents-swarm.spec.md`
  lines: 10-18
  symbol: `FEAT-463`
- path: `sdd/proposals/workingmemory-toolkit.proposal.md`
  lines: 11-24
  symbol: `Closed decisions`

## Notes

- Bus pattern for the local protocol should follow FEAT-710/711: Redis Streams transport, producer outbox for at-least-once, envelope `event_id` dedup — the parent brainstorm's "idempotency key + dead-letter" maps onto this; the "RPC-on-bus (reply_to, correlation)" pattern is still NOT defined anywhere.
- FEAT-710 §8 Q2 decided telemetry must not share the orchestrator's bus; an inter-agent carrier bus would be a third instance or must justify sharing.
- "AuditLedger" never appears in SDD doc commits — the parent brainstorm's "signed, append-only AuditLedger already defined for ai-parrot" needs code-level verification.
- [cross-lane: type=grep, intent=grep 'AuditLedger|audit_ledger' across packages to confirm the ledger the brainstorms assume exists]
- [cross-lane: type=read, intent=read ai-parrot-server/src/parrot/autonomous/orchestrator.py around :245 for the EventBus construction + topic naming]
