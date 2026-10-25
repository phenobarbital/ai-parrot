---
id: FW-005
query_id: Q004
type: wiki_page
intent: "Verify the brainstorm's claim 'no Matrix integration exists' — orient on parrot.integrations.matrix."
executed_at: 2026-10-25T22:46:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# FW-005 — CONTRADICTS brainstorm: a substantial Matrix integration exists (client, AppService, m.parrot.* events, room-state cards, A2A transport, swarm toolkit, three specs)

## Summary

The brainstorm's VERIFY item 'no Matrix integration exists' is FALSE. `packages/ai-parrot-integrations/src/parrot/integrations/matrix/` ships: `client.py::MatrixClientWrapper` over **mautrix** (`send_text, edit_message, send_event(room_id, event_type, content), set_room_state(room_id, event_type, content, state_key), get_room_state_event, on_message, on_custom_event(event_type, cb)`); `appservice.py::MatrixAppService` (virtual MXID per agent via `register_agent`, `send_custom_event_as_agent`, `set_room_state_as_bot/get_room_state_as_bot`, `set_custom_event_callback` for inbound `m.parrot.*`); `hook.py::MatrixHook(BaseHook)` — a **navigator_eventbus** hook (auto-registers with `HookRegistry`, `room_routing` → agent/crew); `events.py::ParrotEventType` with the custom namespace already chosen: message events `m.parrot.task / m.parrot.result / m.parrot.status / m.parrot.feedback` and **state events** `m.parrot.agent_card / m.parrot.channel / m.parrot.tunnel` (state_key=''), plus Pydantic contents `AgentCardEventContent, TaskEventContent, ResultEventContent, StatusEventContent, FeedbackEventContent, ChannelStateContent, TunnelStateContent` and the `AgentAnswer` envelope; `a2a_transport.py::MatrixA2ATransport` (`publish_card` → room state, `discover_card`, `send_task/send_result/send_status`, `wait_for_result(room_id, task_id)`); `crew/registry.py::MatrixCrewRegistry` (`MatrixAgentCard{agent_name, display_name, mxid, status ready|busy|offline, current_task, skills}`, `is_human(mxid)` classification); `crew/delegation.py::HybridDelegator`; `crew/swarm_toolkit.py::AgentSwarmToolkit` (FW-003). Governing SDD docs: `sdd/specs/integrations-matrix-multi.spec.md` (FEAT-044), `sdd/specs/matrix-collaborative-crew.spec.md` (FEAT-195, approved 2026-05-26 — explicitly REJECTED 'event-driven pub/sub via m.parrot.* as the primary communication path' and 'extending AgentCrew with Matrix awareness'), `sdd/proposals/matrix-agents-swarm.brainstorm.md` (FEAT-463). Docs/examples: `docs/integrations/matrix/CLIENTS.md`, `examples/matrix_crew/`, `examples/matrix_swarm/`. The brainstorm's open question 'custom event types under ai.parrot.* vs m.room.message msgtype' is therefore already decided in code as `m.parrot.*`, and 'room state events as blackboard' already has precedent (`agent_card`, `channel`, `tunnel` state events).

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/client.py`
  lines: 1-60
  symbol: `MatrixClientWrapper`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/matrix/client.py (score=1.00)
  excerpt: |
    from mautrix.client import Client as MautrixClient
    class MatrixClientWrapper:  # send_text, edit_message, send_event, set_room_state, get_room_state_event, on_message, on_custom_event
- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/appservice.py`
  lines: 1-70
  symbol: `MatrixAppService`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/matrix/appservice.py (score=0.38)
  excerpt: |
    Virtual MXIDs for each registered agent; Event routing from homeserver push to agents;
    HookEvent emission compatible with AutonomousOrchestrator
    set_custom_event_callback(callback): Set the callback for incoming custom m.parrot.* events
- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/hook.py`
  lines: 1-60
  symbol: `MatrixHook`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/matrix/hook.py (score=0.70)
  excerpt: |
    from navigator_eventbus.hooks.base import BaseHook, HookRegistry
    class MatrixHook(BaseHook): hook_type = HookType.MATRIX  # room_routing -> agent/crew
- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py`
  lines: 27-41
  symbol: `ParrotEventType`
  excerpt: |
    class ParrotEventType:
        AGENT_CARD = 'm.parrot.agent_card'   # state event
        TASK = 'm.parrot.task'; RESULT = 'm.parrot.result'; STATUS = 'm.parrot.status'; FEEDBACK = 'm.parrot.feedback'
        CHANNEL = 'm.parrot.channel'; TUNNEL = 'm.parrot.tunnel'   # state events
- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py`
  lines: 89-283
  symbol: `AgentCardEventContent / TaskEventContent / ResultEventContent / StatusEventContent / AgentAnswer / FeedbackEventContent / ChannelStateContent / TunnelStateContent`
  excerpt: |
    class AgentCardEventContent(BaseModel)  # l.89
    class TaskEventContent(BaseModel)       # l.110
    class ResultEventContent(BaseModel)     # l.131
    class AgentAnswer(BaseModel)            # l.165 — fixed envelope returned by ask_agent
    class ChannelStateContent(BaseModel)    # l.269 (state_key='')
    class TunnelStateContent(BaseModel)     # l.283
- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/a2a_transport.py`
  lines: 1-40
  symbol: `MatrixA2ATransport`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/matrix/a2a_transport.py (score=0.51)
  excerpt: |
    class MatrixA2ATransport:  # publish_card(room_id, card_data) -> room state; discover_card; send_task; send_result; send_status; wait_for_result(room_id, task_id)
- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/registry.py`
  lines: 1-45
  symbol: `MatrixCrewRegistry / MatrixAgentCard`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/registry.py
  excerpt: |
    class MatrixAgentCard(BaseModel): agent_name, display_name, mxid, status ('ready | busy | offline'), current_task, skills: List[str]
    class MatrixCrewRegistry: register/unregister/update_status/get/get_by_mxid/all_agents/is_human
- path: `sdd/specs/matrix-collaborative-crew.spec.md`
  lines: 1-60
  symbol: `FEAT-195 Matrix Collaborative Multi-Agent Crew (Non-Goals)`
  wiki_page_id: file:sdd/specs/matrix-collaborative-crew.spec.md
  excerpt: |
    Non-Goals: Modifying or extending AgentCrew with Matrix awareness (rejected, Option B);
    Event-driven pub/sub orchestration via m.parrot.* custom events as the primary communication path (rejected, Option C)
- path: `sdd/specs/integrations-matrix-multi.spec.md`
  lines: n/a
  symbol: `FEAT-044 Matrix Multi-Agent Crew Integration`
  wiki_page_id: file:sdd/specs/integrations-matrix-multi.spec.md (score=0.82)
- path: `sdd/proposals/matrix-agents-swarm.brainstorm.md`
  lines: n/a
  symbol: `FEAT-463 Matrix Agents Swarm brainstorm`
  wiki_page_id: file:sdd/proposals/matrix-agents-swarm.brainstorm.md (score=0.52)
- path: `docker-compose.matrix.yml`
  lines: n/a
  symbol: `local homeserver stack (repo root)`

## Notes

FEAT-195's recorded rejection of 'm.parrot.* pub/sub as the primary path' is a prior decision the new proposal must either respect (Matrix = one carrier, human-readable `body` mandatory) or explicitly revisit. `[cross-lane: type=git_log, intent=when FEAT-044/195/463 landed and whether matrix/ is still active]`. `[cross-lane: type=read, intent=events.py 89-165 field lists of TaskEventContent/ResultEventContent/AgentCardEventContent to compare with the proposed envelope fields]`.
