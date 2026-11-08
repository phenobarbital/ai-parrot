---
id: F038
query_id: Q005
type: wiki_query
intent: "Orient: event bus transports available in-repo (eventbus v2, telemetry fan-out, Squawk/Roost inter-agent protocol)."
executed_at: 2026-11-07T01:23:54Z
duration_ms: 1200
parent_id: null
depth: 1
merged_from: [FW-009]
---

# F038 — The in-repo bus is navigator_eventbus (Redis Streams) wrapped by Roost's build_roost_bus (requires PARROT_ROOST_BUS_URL); Roost gives typed performatives + subscribe, Squawk is an optional satellite — none of it is reachable from the sdd-worker sandbox or wired into SDD scripts today

## Summary

Q005 hits: TASK-4722 "Envelope codec (JSON fallback) and navigator-eventbus carrier (M9)" (1.00), `wiki/mcp/roost/README.md` (0.56), `sdd/specs/local-inter-agent.spec.md` (FEAT-747), memory `mem-6b4725c2f2d2` (FEAT-746 Squawk: contract in `parrot/interagent/`, transport in the `ai-parrot-squawk` satellite). `parrot/roost/carriers/bus.py:build_roost_bus()` (L201-220) builds `navigator_eventbus.EventBus(redis_url=PARROT_ROOST_BUS_URL, transport="streams", publish_only=False, channel_prefix="roost:", outbox=/tmp/parrot-roost-<pid>.db)` and raises if the URL is missing or the backend is not `RedisStreamsBackend`. Roost: `RoostMessage(performative=Performative.QUERY|INFORM|REQUEST|CFP|SUBSCRIBE…, protocol, conversation_id, sender, receivers, content)` sent through `RoostEndpoint` (`send, inform, request, query, cfp, subscribe, cancel`); PBAC gating fails closed; blackboard with CAS versions; four carriers (`carriers.md`). Roost degrades without Squawk. For escrow v1 a Redis bus is an optional transport: the committed/local ledger journal is already an append-only event stream the host can tail, and the sandbox has no network beyond `gh`.

## Citations

- path: `packages/ai-parrot/src/parrot/roost/carriers/bus.py`
  lines: 201-220
  symbol: `build_roost_bus`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/roost/carriers/bus.py#build_roost_bus
  score: 0.18
  excerpt: |
    def build_roost_bus() -> "EventBus":
        from navigator_eventbus import EventBus
        redis_url = _config_value("PARROT_ROOST_BUS_URL")
        if not redis_url: raise RuntimeError("PARROT_ROOST_BUS_URL is required for the Roost event bus")
        bus = EventBus(redis_url=redis_url, transport="streams", publish_only=False,
                       channel_prefix=channel_prefix, outbox=outbox_path)
- path: `packages/ai-parrot/src/parrot/roost/carriers/bus.py`
  lines: 1-1
  symbol: `EventBusCarrier.__init__`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/roost/carriers/bus.py#EventBusCarrier.__init__
  excerpt: |
    Create a carrier over a bus that supports both publish and subscribe.
- path: `wiki/mcp/roost/README.md`
  lines: 1-45
  symbol: `Roost — local inter-agent sub-protocol`
  wiki_page_id: file:wiki/mcp/roost/README.md
  score: 0.56
  excerpt: |
    Roost never imports `parrot.squawk` at module level ... Without the satellite Roost **degrades, it does not fail**
    msg = RoostMessage(performative=Performative.QUERY, protocol=InteractionProtocol.QUERY, conversation_id="c-1",
                       sender=AgentAddress(name="planner"), receivers=[AgentAddress(name="analyst")], content={...})
    Send it through the agent's `RoostEndpoint` (`send`, `inform`, `request`, `query`, `cfp`, `subscribe`, `cancel`).
- path: `packages/ai-parrot/src/parrot/roost/messages.py`
  lines: 1-1
  symbol: `RoostMessage`
- path: `packages/ai-parrot/src/parrot/roost/performatives.py`
  lines: 1-1
  symbol: `Performative`
- path: `packages/ai-parrot/src/parrot/interagent/`
  lines: 1-1
  symbol: `interagent (Squawk core contract)`
  wiki_page_id: dir:packages/ai-parrot/src/parrot/interagent
- path: `sdd/specs/local-inter-agent.spec.md`
  lines: 1-1
  symbol: `FEAT-747 Roost spec`
  wiki_page_id: file:sdd/specs/local-inter-agent.spec.md
  score: 0.53

## Notes

TASK-4736 (G6) spiked a Call/Result envelope on navigator-eventbus Streams with reply_to/correlation/dedup/DLQ — reusable shape for `work.completed` → verdict reply if a bus is chosen. [cross-lane: type=grep, intent=codebase lane Q033 should confirm whether any `parrot/sdd` or `flows/dev_loop` code publishes to navigator_eventbus today (expected: none).]
