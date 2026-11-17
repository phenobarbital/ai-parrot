---
id: F005
query_id: Q027, Q002
type: read, wiki_page
intent: "Read the crew hand-off code around the matches in Q026 to see the exact type passed between agents."
executed_at: 2026-10-25T23:08:35Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: FC-006, FW-002
---

# F005 — AgentCrew hand-off between agents is a rendered prompt string

## Summary

**[FC-006] AgentCrew hand-off between agents is a rendered prompt string** — Q026 grep located `run_sequential` (1744), `run_loop` (2090, `max_iterations: int = 2`), `run_parallel` (2587), `run_flow` (2933, `max_iterations: int = 100`, raises RuntimeError past it) and a `previous_result` truncation at 3750-3753. In `run_sequential` the hand-off is a **text prompt**: agent i>0 receives either `current_input` (previous agent's output as text) or an f-string `Original query / Previous processing: {context_summary} / Current task`. A `FlowContext` is created per run with `shared_data={**kwargs, 'execution_memory': ...}`. The LLM on both ends re-reads JSON/text; no typed object crosses the boundary.

**[FW-002] AgentCrew passes results between agents as TEXT (extracted string + human-readable summary); loop stop is LLM-evaluated** — `AgentCrew` (`bots/flows/crew/crew.py`) has `run_sequential / run_loop / run_parallel / run_flow / run`. Hand-off is textual: `_extract_result(response)` ('Extract result string from response'), `_build_context_summary(context)` ('human-readable summary of results accumulated so far'), `_truncate_text`, `_build_shared_state_summary(shared_state)`, `_build_loop_first_agent_prompt`. Loop termination: `run_loop(initial_task, condition, max_iterations, ...)` with `_evaluate_loop_condition()` = 'Ask the configured LLM whether the loop condition has been satisfied' (an LLM wake per iteration). Agents are exposed to the orchestrating LLM via `_register_agents_as_tools()` (AgentTool, FW-003); deterministic members exist via `add_tool_node(tool, node_id)`. State is `FlowContext` (TASK-980) with `shared_data`; results are `NodeResult`/`FlowResult`. Imports `ToolManager`, `AgentTool`, `AIMessage`, `AgentResponse`, `AgentStatus`. Confirms the source's premise: inter-agent traffic inside a crew is serialized text plus an LLM turn on both ends; there is no typed performative, no reply-obligation semantics, no per-conversation state machine.


## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: 1744-1756
  symbol: `AgentCrew.run_sequential`
  excerpt: |
    async def run_sequential(self, query: str, user_id: str = None, session_id: str = None,
        pass_full_context: bool = True, generate_summary: bool = True, synthesis_prompt=None,
        agent_sequence: List[str] = None, max_tokens: int = 8192, temperature: float = 0.1,
        model: Optional[str] = "gemini-2.5-pro", **kwargs) -> FlowResult:

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: 1825-1831
  symbol: `AgentCrew.run_sequential (context init)`
  excerpt: |
    current_input = query
    context = FlowContext(initial_task=query,
        shared_data={**kwargs, "execution_memory": self.execution_memory})

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: 1862-1876
  symbol: `AgentCrew.run_sequential (hand-off)`
  excerpt: |
    elif pass_full_context:
        context_summary = self._build_context_summary(context)
        agent_input = f"""Original query: {query}
    Previous processing:
    {context_summary}
    
    Current task: {current_input}"""
    else:
        agent_input = current_input

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: 2090-2094
  symbol: `AgentCrew.run_loop`
  excerpt: |
    async def run_loop(self, ..., max_iterations: int = 2,

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: 2933-2936
  symbol: `AgentCrew.run_flow`
  excerpt: |
    async def run_flow(self, ..., max_iterations: int = 100,

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: 3037-3077
  symbol: `AgentCrew.run_flow (iteration cap)`
  excerpt: |
    while iteration < max_iterations:
    ...
    if iteration >= max_iterations:
        ... f"Workflow exceeded max iterations ({max_iterations}). "

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: 3745-3753
  symbol: `AgentCrew._build_reexecution_prompt`
  excerpt: |
    f"{status_emoji} **{agent_info['agent_name']}** " f"(tool: `{agent_info['tool_name']}`)"
    prev_result = str(agent_info["previous_result"])
    if len(prev_result) > 200:
        prev_result = f"{prev_result[:200]}..."

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: 1-60
  symbol: `AgentCrew (module docstring + imports)`
  wiki_page_id: file:packages/ai-parrot/src/parrot/bots/flows/crew/crew.py (score=0.28)
  excerpt: |
    TASK-980: AgentContext removed; sequential/loop/parallel modes now use FlowContext
    from ....tools.manager import ToolManager
    from ....tools.agent import AgentTool
    from ....models.responses import AIMessage, AgentResponse

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: n/a (API outline)
  symbol: `AgentCrew._extract_result`
  excerpt: |
    def _extract_result(self, response): Extract result string from response.

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: n/a (API outline)
  symbol: `AgentCrew._build_context_summary`
  excerpt: |
    def _build_context_summary(self, context): Build a human-readable summary of results accumulated so far.

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: n/a (API outline)
  symbol: `AgentCrew._evaluate_loop_condition`
  excerpt: |
    def _evaluate_loop_condition(self): Ask the configured LLM whether the loop condition has been satisfied.

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: n/a (API outline)
  symbol: `AgentCrew.run_loop`
  excerpt: |
    def run_loop(self, initial_task, condition, max_iterations, user_id, session_id, agent_sequence, pass_full_context, ...)

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: n/a (API outline)
  symbol: `AgentCrew._register_agents_as_tools / add_tool_node`

- path: `docs/orchestration/agentcrew.md`
  lines: n/a
  symbol: `AgentCrew User Guide`
  wiki_page_id: file:docs/orchestration/agentcrew.md (score=0.39)

## Notes

[FC-006] Q040 (grep `max_iterations|max_hops|hop_limit|budget|max_turns|max_steps` over bots/flows): crew.py 11 hits, flow/flow.py 1, core/node.py 1, plan/facets.py 1, plan/delegate/node.py 1, crew/result_infographic.py 1 — iteration caps per run, no per-conversation hop budget or token budget. Line 3745 shows crew agents are re-exposed to the LLM as tools (`tool: {tool_name}`) in the re-execution prompt.

[FW-002] Line numbers for the hand-off methods were not confirmed in this lane (API outline only). `[cross-lane: type=grep, intent=line ranges for _extract_result/_build_context_summary/_evaluate_loop_condition in crew.py]` (Q026/Q027 cover this). Related docs: `docs/architecture/07-agentcrew.md`, `sdd/specs/agentcrew-hooks.spec.md` (on_complete/on_error hooks exist — a telemetry attach point).

[citation-check: stale] packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:3745-3753 — lines sit inside `_build_ask_user_prompt` (def at l.3647); `_build_reexecution_prompt` does not exist. run_sequential/run_loop/run_flow/_extract_result/_build_context_summary/_evaluate_loop_condition/_register_agents_as_tools/add_tool_node all verified at the cited lines
