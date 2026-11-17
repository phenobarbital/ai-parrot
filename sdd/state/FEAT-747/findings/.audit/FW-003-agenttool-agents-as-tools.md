---
id: FW-003
query_id: Q011
type: wiki_query
intent: "Orient: existing tools that let one agent call another (delegate, ask_agent, crew tools)."
executed_at: 2026-10-25T22:46:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# FW-003 — Existing agent-to-agent tools: AgentTool (text question), AgentSwarmToolkit.ask_agent (Matrix tunnel, hop-limited), HybridDelegator (m.parrot.task/result)

## Summary

Three existing mechanisms let one agent call another, all text-in/text-out and all waking the callee's LLM: (1) `parrot/tools/agent.py::AgentTool` wraps any `AbstractBot` as a tool with `QuestionInput(question: str, mode: replace|append, include_previous_results: bool)`; `AgentContext` dataclass carries `user_id, session_id, original_query, conversation_history, shared_data, agent_results, metadata` between agents. (2) `integrations/matrix/crew/swarm_toolkit.py::AgentSwarmToolkit` (FEAT-463) exposes `ask_agent(agent, question, expected_schema, timeout)`, `send_feedback`, `list_agents`, `list_channels`, `post_to_channel`; `ask_agent` already implements several of the brainstorm's gating ideas: self-ask rejection, unknown-agent envelope, a **hop counter** propagated via ContextVar (`ctx.current_hops`), `origin_session`, a `hop_limit` status, and a fixed `AgentAnswer{answer, confidence, sources, metadata}` envelope validated against an optional JSON Schema. (3) `integrations/matrix/crew/delegation.py::HybridDelegator` sends `m.parrot.task` and awaits the matching `m.parrot.result` (request/reply by task_id with timeout). None of them types the *intent* (performative) or enforces a protocol state machine; the reply obligation is implicit (every ask awaits an answer).

## Citations

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

## Notes

The hop counter + status enum in `ask_agent` is the closest existing precedent for the brainstorm's 'hop budget → failure(HOP_LIMIT)' rule; a local protocol should generalize it rather than add a second one. `sdd/tasks/completed/TASK-2483-agent-swarm-toolkit.md` and `TASK-1300-hybrid-tool-delegation.md` document the design. `[cross-lane: type=read, intent=matrix/crew/tunnel.py and matrix/crew/context.py — how hops/origin_session ContextVars and the hop limit are enforced]`.
