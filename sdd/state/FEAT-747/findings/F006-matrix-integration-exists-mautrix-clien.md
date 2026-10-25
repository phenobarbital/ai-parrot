---
id: F006
query_id: Q029, Q029, Q031, Q052, Q055, Q011, Q004
type: read, read, grep, git_log, git_log, wiki_query, wiki_page
intent: "Read the Matrix integration main module: client library used, event types handled, room state usage, whether custom event types exist."
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: FC-007, FC-008, FC-010, FG-003, FG-006, FW-003, FW-005
---

# F006 — Matrix integration EXISTS: mautrix client, m.parrot.* events, room state, A2A transport

## Summary

**[FC-007] Matrix integration EXISTS: mautrix client, m.parrot.* events, room state, A2A transport** — Contradicts the brainstorm's VERIFY line 'no Matrix integration exists'. `parrot.integrations.matrix` (ai-parrot-integrations) ships `MatrixClientWrapper` over **mautrix-python**, `MatrixAppService` (virtual MXIDs per agent), `MatrixStreamHandler`, `MatrixA2ATransport`, and a custom event namespace `m.parrot.*`: message events `task`/`result`/`status`/`feedback` and **state events** `agent_card`/`channel`/`tunnel` (replace-not-append semantics come from Matrix state). The client exposes `send_event`, `set_room_state`, `get_room_state_event`, `on_message`, `on_custom_event`. `MatrixA2ATransport` maps A2A discovery to `m.parrot.agent_card` room state and tasks/results to message events with a correlation future.

**[FC-008] Matrix swarm already implements ask_agent tunnels, delegation, hop limit, status registry** — The `matrix/crew/` sub-package (FEAT-044 crew, FEAT-463 swarm) is the closest existing local inter-agent protocol: `AgentSwarmToolkit` is attached per agent to its `ToolManager` and exposes LLM tools `ask_agent`, `send_feedback`, `list_agents`, `list_channels`, `post_to_channel`. `ask_agent` resolves the peer in `MatrixCrewRegistry` (by **name**, rejects self), opens a private 2-agent tunnel room (`TunnelRegistry.get_or_create`), sends `m.parrot.task` and awaits `m.parrot.result` through a correlation-id future, propagating `hops` and `origin_session` from ContextVars — status codes include `hop_limit`, `timeout`, `schema_error`. `HybridDelegator` does the same with a visible human-readable message plus the custom event. `MatrixCoordinator` keeps a pinned status board. Session state (`CollaborativeSessionState`) is a phase enum + per-round text results.

**[FC-010] navigator-eventbus is already the hook/telemetry bus across parrot** — `eventbus|EventBus|navigator_eventbus|navigator\.eventbus` matches ~70 source files (plus duplicated `build/lib*` copies, which are stale artifacts). Clusters: (1) `parrot/core/hooks/*` — every inbound hook (`matrix`, `messaging` Telegram/WhatsApp/MSTeams, `jira_webhook`, `github_webhook`, `imap`, `postgres`, `sharepoint`, `file_upload`) subclasses `navigator_eventbus.hooks.base.BaseHook`; (2) `parrot/core/events/lifecycle/*` + `observability/fanout.py`/`bootstrap.py` — lifecycle telemetry fan-out; (3) `ai-parrot-server/parrot/autonomous/{evb,orchestrator,webhooks}.py` — autonomous orchestrator listens on the bus; (4) `integrations/matrix/hook.py` — `MatrixHook(BaseHook)` registered in `HookRegistry`. The bus is used for hooks and telemetry, not yet as an agent-to-agent carrier.

**[FG-003] Matrix integration history: FEAT-044 → FEAT-195 → FEAT-463 (Aug 2026) — a full agent swarm over Matrix already exists** — Commits in the window cluster on 2026-08-26 (FEAT-463 matrix-agents-swarm implementation + two code-review fix rounds) with a lint pass on 2026-09-19; earlier work (FEAT-044 `integrations-matrix-multi`, FEAT-195 `matrix-collaborative-crew`) predates the window per the spec header. The package `packages/ai-parrot-integrations/src/parrot/integrations/matrix/` has 15+ files: `appservice.py`, `events.py`, `registration.py`, and `crew/{channels,config,context,coordinator,crew_wrapper,registry,session,swarm,swarm_toolkit,transport,tunnel}.py`. The brainstorm's "VERIFY: no Matrix integration exists" is **false**. The approved FEAT-463 spec (read, 4 reads budget) already defines: custom event namespace `m.parrot.*` (`agent_card`, `task`, `result`, `status`, `channel`, `tunnel`, `feedback`), **state events** for channel/tunnel (replaced, not appended), `TaskEventContent.correlation_id/hops/origin_session/expected_schema`, `TunnelConfig.max_hops=3`, `AgentSwarmToolkit.ask_agent()`, `MatrixCrewRegistry` (agent cards with skills/status), `ChannelManager` with `answer_policy: mention|swarm|silent`, `MatrixCollaborativeSession` and a `docker-compose.matrix.yml` dev stack with Element + mautrix bridges.

**[FG-006] Prior SDD decisions: FEAT-463/464 Matrix swarm, FEAT-710/711 eventbus fan-out, WorkingMemory task memory, FEAT-575/425 crew, FEAT-436 registry drift** — ~60 SDD-doc commits matched in 365 days. Directly relevant prior decisions: (1) **FEAT-463 matrix-agents-swarm** + **FEAT-464 matrix-swarm-sample** (approved 2026-08-26) — see FG-003. (2) **FEAT-710 parrot-telemetry-event-fanout** (approved 2026-10-20, rev 0.4 on 10-21) — chooses *navigator-eventbus* `EventBus(transport="streams", publish_only=True, outbox=<sqlite>)` with at-least-once delivery, dedup by envelope `event_id`, a *dedicated* bus instance (never the autonomous orchestrator's bus), `EventRegistry.attach_bus()` + serializer hook delivered upstream as **FEAT-711** in `../navigator-eventbus`; the server's `autonomous/orchestrator.py:245` already constructs an `EventBus`. (3) **workingmemory-toolkit proposal** (2026-09-08) — see FG-004. (4) Crew specs FEAT-575 (handler default key), FEAT-425 agentcrew-tales-research; (5) FEAT-436 sync-tool-registry-drift, FEAT-427 (TOOL_REGISTRY generation). No SDD document covers a performative layer, an inter-agent grant, or a shared blackboard. No match for "audit ledger"/"AuditLedger" in SDD doc commit messages.

**[FW-003] Existing agent-to-agent tools: AgentTool (text question), AgentSwarmToolkit.ask_agent (Matrix tunnel, hop-limited), HybridDelegator (m.parrot.task/result)** — Three existing mechanisms let one agent call another, all text-in/text-out and all waking the callee's LLM: (1) `parrot/tools/agent.py::AgentTool` wraps any `AbstractBot` as a tool with `QuestionInput(question: str, mode: replace|append, include_previous_results: bool)`; `AgentContext` dataclass carries `user_id, session_id, original_query, conversation_history, shared_data, agent_results, metadata` between agents. (2) `integrations/matrix/crew/swarm_toolkit.py::AgentSwarmToolkit` (FEAT-463) exposes `ask_agent(agent, question, expected_schema, timeout)`, `send_feedback`, `list_agents`, `list_channels`, `post_to_channel`; `ask_agent` already implements several of the brainstorm's gating ideas: self-ask rejection, unknown-agent envelope, a **hop counter** propagated via ContextVar (`ctx.current_hops`), `origin_session`, a `hop_limit` status, and a fixed `AgentAnswer{answer, confidence, sources, metadata}` envelope validated against an optional JSON Schema. (3) `integrations/matrix/crew/delegation.py::HybridDelegator` sends `m.parrot.task` and awaits the matching `m.parrot.result` (request/reply by task_id with timeout). None of them types the *intent* (performative) or enforces a protocol state machine; the reply obligation is implicit (every ask awaits an answer).

**[FW-005] CONTRADICTS brainstorm: a substantial Matrix integration exists (client, AppService, m.parrot.* events, room-state cards, A2A transport, swarm toolkit, three specs)** — The brainstorm's VERIFY item 'no Matrix integration exists' is FALSE. `packages/ai-parrot-integrations/src/parrot/integrations/matrix/` ships: `client.py::MatrixClientWrapper` over **mautrix** (`send_text, edit_message, send_event(room_id, event_type, content), set_room_state(room_id, event_type, content, state_key), get_room_state_event, on_message, on_custom_event(event_type, cb)`); `appservice.py::MatrixAppService` (virtual MXID per agent via `register_agent`, `send_custom_event_as_agent`, `set_room_state_as_bot/get_room_state_as_bot`, `set_custom_event_callback` for inbound `m.parrot.*`); `hook.py::MatrixHook(BaseHook)` — a **navigator_eventbus** hook (auto-registers with `HookRegistry`, `room_routing` → agent/crew); `events.py::ParrotEventType` with the custom namespace already chosen: message events `m.parrot.task / m.parrot.result / m.parrot.status / m.parrot.feedback` and **state events** `m.parrot.agent_card / m.parrot.channel / m.parrot.tunnel` (state_key=''), plus Pydantic contents `AgentCardEventContent, TaskEventContent, ResultEventContent, StatusEventContent, FeedbackEventContent, ChannelStateContent, TunnelStateContent` and the `AgentAnswer` envelope; `a2a_transport.py::MatrixA2ATransport` (`publish_card` → room state, `discover_card`, `send_task/send_result/send_status`, `wait_for_result(room_id, task_id)`); `crew/registry.py::MatrixCrewRegistry` (`MatrixAgentCard{agent_name, display_name, mxid, status ready|busy|offline, current_task, skills}`, `is_human(mxid)` classification); `crew/delegation.py::HybridDelegator`; `crew/swarm_toolkit.py::AgentSwarmToolkit` (FW-003). Governing SDD docs: `sdd/specs/integrations-matrix-multi.spec.md` (FEAT-044), `sdd/specs/matrix-collaborative-crew.spec.md` (FEAT-195, approved 2026-05-26 — explicitly REJECTED 'event-driven pub/sub via m.parrot.* as the primary communication path' and 'extending AgentCrew with Matrix awareness'), `sdd/proposals/matrix-agents-swarm.brainstorm.md` (FEAT-463). Docs/examples: `docs/integrations/matrix/CLIENTS.md`, `examples/matrix_crew/`, `examples/matrix_swarm/`. The brainstorm's open question 'custom event types under ai.parrot.* vs m.room.message msgtype' is therefore already decided in code as `m.parrot.*`, and 'room state events as blackboard' already has precedent (`agent_card`, `channel`, `tunnel` state events).


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

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py`
  lines: 24-51
  symbol: `AgentSwarmToolkit`
  excerpt: |
    class AgentSwarmToolkit(AbstractToolkit):
        def __init__(self, agent_name: str, tunnels: TunnelRegistry, registry: MatrixCrewRegistry,
                     channels: ChannelManager, appservice: MatrixAppService, **kwargs)

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py`
  lines: 53-98
  symbol: `AgentSwarmToolkit.ask_agent`
  excerpt: |
    if agent == self._agent_name:
        return {"status": "self_ask_rejected"}
    if await self._registry.get(agent) is None:
        return {"status": "unknown_agent", "available": [...]}
    tunnel = await self._tunnels.get_or_create(self._agent_name, agent)
    ans = await tunnel.ask(self._agent_name, agent, question, expected_schema=expected_schema,
        timeout=timeout, hops=ctx.current_hops.get(), origin_session=ctx.current_session.get())
    return ans.model_dump()

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py`
  lines: 160-178
  symbol: `AgentSwarmToolkit.post_to_channel`
  excerpt: |
    if not self._channels.is_member(self._agent_name, channel):
        return f"forbidden: '{self._agent_name}' is not a member of channel '{channel}'"

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/tunnel.py`
  lines: 1-10
  symbol: `module docstring`
  excerpt: |
    A *tunnel* is a lazily created, private 2-member Matrix room shared by an unordered pair of agents,
    carrying m.parrot.task / m.parrot.result / m.parrot.feedback events. AgentTunnel.ask() sends a task
    and awaits the matching result via a correlation-future ... keyed by correlation_id

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/tunnel.py`
  lines: 318-338
  symbol: `TunnelRegistry.register_future / discard_future`
  excerpt: |
    def register_future(self, correlation_id: str) -> asyncio.Future:
        fut = asyncio.get_running_loop().create_future()
        self._futures[correlation_id] = fut

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/delegation.py`
  lines: 31-47
  symbol: `DelegationRequest`
  excerpt: |
    requester_name: str; target_agent: str; task_description: str; room_id: str; context: Optional[str]

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/delegation.py`
  lines: 71-151
  symbol: `HybridDelegator.delegate`
  excerpt: |
    # 2. Post visible message as the requester ... "Asking {pill} to: {request.task_description}"
    # 3. Send m.parrot.task custom event
    task_content = TaskEventContent(task_id=task_id, content=request.task_description, target_agent=request.target_agent, context_id=request.context)
    # 4. Wait for m.parrot.result with timeout
    result = await self._wait_for_result(task_id, timeout)

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/registry.py`
  lines: 16-39
  symbol: `MatrixAgentCard`
  excerpt: |
    agent_name: str; display_name: str; mxid: str
    status: str = "offline"   # ready | busy | offline
    current_task: Optional[str]; skills: List[str]; joined_at; last_seen

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/registry.py`
  lines: 67-92
  symbol: `MatrixCrewRegistry`
  excerpt: |
    self._agents: Dict[str, MatrixAgentCard] = {}  # keyed by agent_name
    self._lock = asyncio.Lock()

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/session_models.py`
  lines: 14-31
  symbol: `SessionPhase`
  excerpt: |
    CREATED / INVESTIGATING / CROSS_POLLINATING / SYNTHESIZING / COMPLETED / FAILED

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/session_models.py`
  lines: 34-57
  symbol: `AgentRoundResult`
  excerpt: |
    result_text: str; event_id: str  # Matrix event ID for reply-to threading

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/coordinator.py`
  lines: 17-116
  symbol: `MatrixCoordinator`
  excerpt: |
    async def on_agent_join / on_agent_leave / on_status_change / refresh_status_board

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/hook.py`
  lines: 1-27
  symbol: `MatrixHook`
  excerpt: |
    Concrete implementation of :class:`~navigator_eventbus.hooks.base.BaseHook`
    from navigator_eventbus.hooks.base import BaseHook, HookRegistry
    from navigator_eventbus.hooks.models import HookType, MatrixHookConfig
    class MatrixHook(BaseHook):

- path: `packages/ai-parrot/src/parrot/core/hooks/messaging.py`
  lines: 21-70
  symbol: `_MessagingHookBase / TelegramHook`
  excerpt: |
    class _MessagingHookBase(BaseHook): ...  class TelegramHook(_MessagingHookBase):

- path: `packages/ai-parrot/src/parrot/observability/fanout.py`
  lines: 1
  symbol: `module`
  excerpt: |
    eventbus fan-out of lifecycle events (FEAT-710)

- path: `packages/ai-parrot-server/src/parrot/autonomous/evb.py`
  lines: 1
  symbol: `module`
  excerpt: |
    autonomous orchestrator event-bus adapter

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

- path: `sdd/proposals/workingmemory-toolkit.proposal.md`
  lines: 11-24
  symbol: `Closed decisions`

- path: `packages/ai-parrot/src/parrot/tools/agent.py`
  lines: 20-55
  symbol: `AgentContext / QuestionInput / AgentTool`
  wiki_page_id: file:packages/ai-parrot/src/parrot/tools/agent.py
  excerpt: |
    @dataclass
    class AgentContext:  # Context passed between agents in orchestration.
        user_id: str; session_id: str; original_query: str
        shared_data: Dict[str, Any]; agent_results: Dict[str, Any]
    class QuestionInput(BaseModel):
        question: str; mode: Optional[Literal['replace','append']]; include_previous_results: bool
    class AgentTool(AbstractTool):  # Wraps any BasicAgent/AbstractBot as a tool

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py`
  lines: 24
  symbol: `AgentSwarmToolkit`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py (score=0.54)
  excerpt: |
    class AgentSwarmToolkit(AbstractToolkit):

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py`
  lines: 53-99
  symbol: `AgentSwarmToolkit.ask_agent`
  excerpt: |
    async def ask_agent(self, agent, question, expected_schema=None, timeout=None) -> dict:
        # metadata.status in: ok | timeout | error | schema_error | hop_limit | unknown_agent | self_ask_rejected
        if agent == self._agent_name: return {'status': 'self_ask_rejected'}
        tunnel = await self._tunnels.get_or_create(self._agent_name, agent)
        ans = await tunnel.ask(self._agent_name, agent, question, expected_schema=expected_schema,
            timeout=timeout, hops=ctx.current_hops.get(), origin_session=ctx.current_session.get())
        return ans.model_dump()

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/swarm_toolkit.py`
  lines: 100-180
  symbol: `AgentSwarmToolkit.send_feedback / list_agents / list_channels / post_to_channel`

- path: `packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/delegation.py`
  lines: 1-80
  symbol: `HybridDelegator / DelegationRequest`
  wiki_page_id: file:packages/ai-parrot-integrations/src/parrot/integrations/matrix/crew/delegation.py (score=1.00)
  excerpt: |
    HybridDelegator bridges the collaborative session layer with the Matrix custom event layer (m.parrot.task / m.parrot.result)
    class DelegationRequest(BaseModel): requester_name, target_agent, task_description, room_id, context
    class HybridDelegator: delegate(request, timeout) ; _wait_for_result(task_id, timeout)

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

[FC-007] Q028 tree: `matrix/{__init__,a2a_transport,appservice,client,events,hook,models,registration,streaming}.py` + `matrix/crew/{channels,config,context,coordinator,crew_wrapper,delegation,mention,registry,session,session_models,swarm,swarm_toolkit,transport,tunnel}.py` (24 files). Event payloads are JSON dicts (`model_dump()`); no protobuf/base64 envelope. `ChannelStateContent.version: int` is the only versioned state. `[cross-lane: type=git_log, intent=FEAT-044 (crew) and FEAT-463 (swarm) history — who/when]`

[FC-008] Key gaps vs. the brainstorm: addressing is by agent *name* (`skills: List[str]` is display-only, not searchable); payloads are text (`question: str`, `result_text: str`, `AgentAnswer` dict); the per-conversation state is a session *phase*, not a per-message protocol FSM; `hops` is propagated but there is no performative. This is a separate registry (`MatrixCrewRegistry`) from core `AgentRegistry`.

[FC-010] Representative tests: `tests/core/hooks/test_hookmanager_eventbus.py`, `tests/core/hooks/test_hookmanager_route_to_bus.py`, `ai-parrot-server/tests/test_orchestrator_eventbus_listener.py`, `ai-parrot-integrations/tests/test_matrix_hook.py`. `[cross-lane: type=wiki_page, intent=navigator-eventbus API surface (publish/subscribe/topics/reply_to) — FW-008 may cover]`

[FG-003] - Directly answers brainstorm open question 7 (Matrix event types): the codebase already chose **custom event types under `m.parrot.*`** plus `m.room.message` for human-readable text; state events already hold roster-like data (`m.parrot.channel`, `m.parrot.tunnel`). An `ai.parrot.*` namespace would be a second convention.
- The Matrix crew already has: hop budget (`max_hops`), correlation ids, a per-crew registry with skills, request/result pairing, answer-policy gating (`mention|swarm|silent`) — i.e. a carrier-specific precursor of performatives + gating. The local protocol spec should subsume it, not duplicate it.
- The spec's `TaskEventContent.content` is free text + `expected_schema` → the LLM wakes on every task; this is exactly the cost the brainstorm attacks.
- [cross-lane: type=read, intent=read matrix/events.py and matrix/crew/tunnel.py to confirm implemented fields (correlation_id, hops) vs spec]
- [cross-lane: type=grep, intent=grep 'answer_policy|max_hops|hops' in integrations/matrix/crew to confirm gating is implemented]

[FG-006] - Bus pattern for the local protocol should follow FEAT-710/711: Redis Streams transport, producer outbox for at-least-once, envelope `event_id` dedup — the parent brainstorm's "idempotency key + dead-letter" maps onto this; the "RPC-on-bus (reply_to, correlation)" pattern is still NOT defined anywhere.
- FEAT-710 §8 Q2 decided telemetry must not share the orchestrator's bus; an inter-agent carrier bus would be a third instance or must justify sharing.
- "AuditLedger" never appears in SDD doc commits — the parent brainstorm's "signed, append-only AuditLedger already defined for ai-parrot" needs code-level verification.
- [cross-lane: type=grep, intent=grep 'AuditLedger|audit_ledger' across packages to confirm the ledger the brainstorms assume exists]
- [cross-lane: type=read, intent=read ai-parrot-server/src/parrot/autonomous/orchestrator.py around :245 for the EventBus construction + topic naming]

[FW-003] The hop counter + status enum in `ask_agent` is the closest existing precedent for the brainstorm's 'hop budget → failure(HOP_LIMIT)' rule; a local protocol should generalize it rather than add a second one. `sdd/tasks/completed/TASK-2483-agent-swarm-toolkit.md` and `TASK-1300-hybrid-tool-delegation.md` document the design. `[cross-lane: type=read, intent=matrix/crew/tunnel.py and matrix/crew/context.py — how hops/origin_session ContextVars and the hop limit are enforced]`.

[FW-005] FEAT-195's recorded rejection of 'm.parrot.* pub/sub as the primary path' is a prior decision the new proposal must either respect (Matrix = one carrier, human-readable `body` mandatory) or explicitly revisit. `[cross-lane: type=git_log, intent=when FEAT-044/195/463 landed and whether matrix/ is still active]`. `[cross-lane: type=read, intent=events.py 89-165 field lists of TaskEventContent/ResultEventContent/AgentCardEventContent to compare with the proposed envelope fields]`.
