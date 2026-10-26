---
id: FC-008
query_id: Q029
type: read
intent: "Read the Matrix crew/swarm layer: how agents already talk to each other over Matrix (tunnels, delegation, registry, hop limits)."
executed_at: 2026-10-26T00:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-008 — Matrix swarm already implements ask_agent tunnels, delegation, hop limit, status registry

## Summary

The `matrix/crew/` sub-package (FEAT-044 crew, FEAT-463 swarm) is the closest existing local inter-agent protocol: `AgentSwarmToolkit` is attached per agent to its `ToolManager` and exposes LLM tools `ask_agent`, `send_feedback`, `list_agents`, `list_channels`, `post_to_channel`. `ask_agent` resolves the peer in `MatrixCrewRegistry` (by **name**, rejects self), opens a private 2-agent tunnel room (`TunnelRegistry.get_or_create`), sends `m.parrot.task` and awaits `m.parrot.result` through a correlation-id future, propagating `hops` and `origin_session` from ContextVars — status codes include `hop_limit`, `timeout`, `schema_error`. `HybridDelegator` does the same with a visible human-readable message plus the custom event. `MatrixCoordinator` keeps a pinned status board. Session state (`CollaborativeSessionState`) is a phase enum + per-round text results.

## Citations

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


## Notes

Key gaps vs. the brainstorm: addressing is by agent *name* (`skills: List[str]` is display-only, not searchable); payloads are text (`question: str`, `result_text: str`, `AgentAnswer` dict); the per-conversation state is a session *phase*, not a per-message protocol FSM; `hops` is propagated but there is no performative. This is a separate registry (`MatrixCrewRegistry`) from core `AgentRegistry`.
