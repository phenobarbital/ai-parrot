---
id: FC-006
query_id: Q027
type: read
intent: "Read the crew hand-off code around the matches in Q026 to see the exact type passed between agents."
executed_at: 2026-10-26T00:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-006 — AgentCrew hand-off between agents is a rendered prompt string

## Summary

Q026 grep located `run_sequential` (1744), `run_loop` (2090, `max_iterations: int = 2`), `run_parallel` (2587), `run_flow` (2933, `max_iterations: int = 100`, raises RuntimeError past it) and a `previous_result` truncation at 3750-3753. In `run_sequential` the hand-off is a **text prompt**: agent i>0 receives either `current_input` (previous agent's output as text) or an f-string `Original query / Previous processing: {context_summary} / Current task`. A `FlowContext` is created per run with `shared_data={**kwargs, 'execution_memory': ...}`. The LLM on both ends re-reads JSON/text; no typed object crosses the boundary.

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


## Notes

Q040 (grep `max_iterations|max_hops|hop_limit|budget|max_turns|max_steps` over bots/flows): crew.py 11 hits, flow/flow.py 1, core/node.py 1, plan/facets.py 1, plan/delegate/node.py 1, crew/result_infographic.py 1 — iteration caps per run, no per-conversation hop budget or token budget. Line 3745 shows crew agents are re-exposed to the LLM as tools (`tool: {tool_name}`) in the re-execution prompt.
