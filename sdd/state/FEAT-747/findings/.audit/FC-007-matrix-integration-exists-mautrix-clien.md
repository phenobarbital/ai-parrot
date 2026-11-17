---
id: FC-007
query_id: Q029
type: read
intent: "Read the Matrix integration main module: client library used, event types handled, room state usage, whether custom event types exist."
executed_at: 2026-10-26T00:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-007 — Matrix integration EXISTS: mautrix client, m.parrot.* events, room state, A2A transport

## Summary

Contradicts the brainstorm's VERIFY line 'no Matrix integration exists'. `parrot.integrations.matrix` (ai-parrot-integrations) ships `MatrixClientWrapper` over **mautrix-python**, `MatrixAppService` (virtual MXIDs per agent), `MatrixStreamHandler`, `MatrixA2ATransport`, and a custom event namespace `m.parrot.*`: message events `task`/`result`/`status`/`feedback` and **state events** `agent_card`/`channel`/`tunnel` (replace-not-append semantics come from Matrix state). The client exposes `send_event`, `set_room_state`, `get_room_state_event`, `on_message`, `on_custom_event`. `MatrixA2ATransport` maps A2A discovery to `m.parrot.agent_card` room state and tasks/results to message events with a correlation future.

## Citations

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/__init__.py`
  lines: 1-10
  symbol: `module docstring`
  excerpt: |
    Provides Matrix-based communication for agents via mautrix-python:
    - MatrixClientWrapper: async client wrapper
    - MatrixStreamHandler: edit-based streaming
    - MatrixA2ATransport: A2A over Matrix events
    - MatrixAppService: Application Service with virtual MXIDs
    - Custom m.parrot.* event types
    - MatrixCrewTransport: multi-agent crew (FEAT-044)

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py`
  lines: 27-40
  symbol: `ParrotEventType`
  excerpt: |
    class ParrotEventType:
        AGENT_CARD = "m.parrot.agent_card"   # State event
        TASK = "m.parrot.task"
        RESULT = "m.parrot.result"
        STATUS = "m.parrot.status"
        FEEDBACK = "m.parrot.feedback"
        CHANNEL = "m.parrot.channel"         # State events
        TUNNEL = "m.parrot.tunnel"

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py`
  lines: 89-165
  symbol: `AgentCardEventContent / TaskEventContent / ResultEventContent / StatusEventContent / AgentAnswer`
  excerpt: |
    class AgentCardEventContent(BaseModel): ...  class TaskEventContent(BaseModel): ...

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/events.py`
  lines: 269-293
  symbol: `ChannelStateContent / TunnelStateContent`
  excerpt: |
    class ChannelStateContent(BaseModel):   # m.parrot.channel, state_key=""
        name: str; visibility: str; answer_policy: str; agents: List[str]; version: int = 1
    class TunnelStateContent(BaseModel):    # m.parrot.tunnel, state_key=""
        agents: List[str]; created_at: datetime; ttl_minutes: int; origin_session: Optional[str]

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/client.py`
  lines: 193-262
  symbol: `MatrixClientWrapper.send_event / set_room_state / get_room_state_event`
  excerpt: |
    async def send_event(self, room_id: str, event_type: str, content: Dict[str, Any]) -> str:
    async def set_room_state(self, room_id, event_type, content, state_key: str = "") -> str:
    async def get_room_state_event(self, room_id, event_type, state_key="") -> Optional[Dict]:

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/client.py`
  lines: 277-303
  symbol: `MatrixClientWrapper.on_message / on_custom_event`
  excerpt: |
    def on_custom_event(self, event_type: str, callback) -> None:
        evt_type = EventType.find(event_type, t_class=EventType.Class.MESSAGE)
        self._client.add_event_handler(evt_type, callback)

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/a2a_transport.py`
  lines: 25-39
  symbol: `MatrixA2ATransport`
  excerpt: |
    - Agent discovery → m.parrot.agent_card state events
    - Task submission → m.parrot.task message events
    - Task results → m.parrot.result message events
    - Status updates → m.parrot.status message events

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/a2a_transport.py`
  lines: 54-110
  symbol: `MatrixA2ATransport.publish_card / discover_card`
  excerpt: |
    content = AgentCardEventContent(**card_data)
    event_id = await self._wrapper.set_room_state(room_id, ParrotEventType.AGENT_CARD, content.model_dump(), state_key=state_key)


## Notes

Q028 tree: `matrix/{__init__,a2a_transport,appservice,client,events,hook,models,registration,streaming}.py` + `matrix/crew/{channels,config,context,coordinator,crew_wrapper,delegation,mention,registry,session,session_models,swarm,swarm_toolkit,transport,tunnel}.py` (24 files). Event payloads are JSON dicts (`model_dump()`); no protobuf/base64 envelope. `ChannelStateContent.version: int` is the only versioned state. `[cross-lane: type=git_log, intent=FEAT-044 (crew) and FEAT-463 (swarm) history — who/when]`
