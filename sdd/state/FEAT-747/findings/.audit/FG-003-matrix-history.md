---
id: FG-003
query_id: Q052
type: git_log
intent: "History of the Matrix integration — when it landed, which FEAT, how complete."
executed_at: 2026-10-25T22:41:00Z
duration_ms: 380
parent_id: null
depth: 0
---

# FG-003 — Matrix integration history: FEAT-044 → FEAT-195 → FEAT-463 (Aug 2026) — a full agent swarm over Matrix already exists

## Summary

Commits in the window cluster on 2026-08-26 (FEAT-463 matrix-agents-swarm implementation + two code-review fix rounds) with a lint pass on 2026-09-19; earlier work (FEAT-044 `integrations-matrix-multi`, FEAT-195 `matrix-collaborative-crew`) predates the window per the spec header. The package `packages/ai-parrot-integrations/src/parrot/integrations/matrix/` has 15+ files: `appservice.py`, `events.py`, `registration.py`, and `crew/{channels,config,context,coordinator,crew_wrapper,registry,session,swarm,swarm_toolkit,transport,tunnel}.py`. The brainstorm's "VERIFY: no Matrix integration exists" is **false**. The approved FEAT-463 spec (read, 4 reads budget) already defines: custom event namespace `m.parrot.*` (`agent_card`, `task`, `result`, `status`, `channel`, `tunnel`, `feedback`), **state events** for channel/tunnel (replaced, not appended), `TaskEventContent.correlation_id/hops/origin_session/expected_schema`, `TunnelConfig.max_hops=3`, `AgentSwarmToolkit.ask_agent()`, `MatrixCrewRegistry` (agent cards with skills/status), `ChannelManager` with `answer_policy: mention|swarm|silent`, `MatrixCollaborativeSession` and a `docker-compose.matrix.yml` dev stack with Element + mautrix bridges.

## Citations

- sha: `59d1d1dfae` date: 2026-09-19 author: Jesus — style(matrix-agents-swarm): FEAT-463 — lint fixes — files: `matrix/crew/session.py`
- sha: `4723c75327` date: 2026-08-26 author: Jesus — fix(matrix-agents-swarm): address remaining code-review important findings — files: `crew/config.py`, `crew/session.py`, `crew/transport.py`, `crew/tunnel.py`
- sha: `2a1caf7800` date: 2026-08-26 author: Jesus — fix(matrix-agents-swarm): address code-review critical/important findings — files: `crew/crew_wrapper.py`, `crew/swarm_toolkit.py`, `crew/tunnel.py`, `events.py`
- sha: `bf5eb4125b` date: 2026-08-26 author: Jesus — style: black formatting — files: all 15 matrix module files (listed below)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py`
  symbol: `ParrotEventType`
  excerpt: |
    # per sdd/specs/matrix-agents-swarm.spec.md:460-467 (verified 2026-08-26)
    AGENT_CARD = "m.parrot.agent_card"; TASK = "m.parrot.task"
    RESULT = "m.parrot.result"; STATUS = "m.parrot.status"
    # FEAT-463 adds: CHANNEL = "m.parrot.channel" (state), TUNNEL = "m.parrot.tunnel" (state), FEEDBACK
- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py`
  symbol: `TaskEventContent`
  excerpt: |
    # spec :87 — task_id, context_id, content, metadata, target_agent, skill_id
    # FEAT-463 adds: correlation_id, hops, origin_session, expected_schema
- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/appservice.py`
  symbol: `MatrixAppService`
  excerpt: |
    # spec :477-500 — send_custom_event_as_agent(agent_name, room_id, event_type, content)  :316
    # set_custom_event_callback(callback)  :444 ; send_reply_as_agent(... reply_to_event_id) :349 (m.in_reply_to)
    # FEAT-463 adds: create_room_as_bot(), set_room_state_as_bot(room_id, event_type, content, state_key="")
- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/tunnel.py`
  symbol: `TunnelRegistry`
  excerpt: |
    # spec :263-279 — AgentTunnel.ask(requester, target, question, *, expected_schema, timeout, hops, origin_session) -> AgentAnswer
    # correlation-future pattern copied from MatrixA2ATransport.wait_for_result (:249)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py`
  symbol: `AgentSwarmToolkit`
  excerpt: |
    # spec :280-291 — ask_agent(agent, question, expected_schema, timeout) -> dict; list_agents(); list_channels(); post_to_channel()
- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/registry.py`
  symbol: `MatrixCrewRegistry`
  excerpt: |
    # spec :514-520 — MatrixAgentCard(agent_name, display_name, mxid, status, current_task, skills, joined_at, last_seen)
    # register/unregister/update_status/get/get_by_mxid/all_agents ; FEAT-463 adds is_human(mxid)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/config.py`
  symbol: `MatrixCrewConfig`
  excerpt: |
    # spec :191-220 — ChannelConfig(answer_policy: mention|swarm|silent), TunnelConfig(max_hops=3, ttl_minutes, default_timeout),
    # CollaborativeConfig(max_rounds, agent_timeout, session_timeout, max_concurrent_sessions, cooldown_seconds)
- path: `sdd/specs/matrix-agents-swarm.spec.md`
  lines: 10-18
  symbol: `FEAT-463`
  excerpt: |
    **Feature ID**: FEAT-463  **Date**: 2026-08-26  **Status**: approved
    **Builds on**: FEAT-044 (`integrations-matrix-multi`), FEAT-195 (`matrix-collaborative-crew`)
- path: `sdd/specs/matrix-agents-swarm.spec.md`
  lines: 28-50
  symbol: `Problem Statement`
  excerpt: |
    `parrot.integrations.matrix` already ships FEAT-044 (AppService virtual users, shared + per-agent rooms,
    `@mention` routing, coordinator status board, `m.parrot.*` A2A events) and FEAT-195 (`!investigate`
    phased sessions, reply-to threading, `HybridDelegator`).
- path: `sdd/specs/matrix-agents-swarm.spec.md`
  lines: 171-186
  symbol: `Integration Points`
- path: `sdd/specs/matrix-swarm-sample.spec.md`
  symbol: `FEAT-464`
  excerpt: |
    (sibling: matrix-swarm-sample — approved 2026-08-26, commits d5362e68cb / 45d468b471)
- path: `docker-compose.matrix.yml`
  excerpt: |
    (FEAT-463 Module 7: synapse, postgres, element-web, profile `bridges` → mautrix-signal/slack/discord)

## Notes

- Directly answers brainstorm open question 7 (Matrix event types): the codebase already chose **custom event types under `m.parrot.*`** plus `m.room.message` for human-readable text; state events already hold roster-like data (`m.parrot.channel`, `m.parrot.tunnel`). An `ai.parrot.*` namespace would be a second convention.
- The Matrix crew already has: hop budget (`max_hops`), correlation ids, a per-crew registry with skills, request/result pairing, answer-policy gating (`mention|swarm|silent`) — i.e. a carrier-specific precursor of performatives + gating. The local protocol spec should subsume it, not duplicate it.
- The spec's `TaskEventContent.content` is free text + `expected_schema` → the LLM wakes on every task; this is exactly the cost the brainstorm attacks.
- [cross-lane: type=read, intent=read matrix/events.py and matrix/crew/tunnel.py to confirm implemented fields (correlation_id, hops) vs spec]
- [cross-lane: type=grep, intent=grep 'answer_policy|max_hops|hops' in integrations/matrix/crew to confirm gating is implemented]
