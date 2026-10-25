---
id: FW-002
query_id: Q002
type: wiki_page
intent: "Orient: how agents talk to each other today inside a crew — output hand-off format between run_sequential/run_parallel steps."
executed_at: 2026-10-25T22:46:00Z
duration_ms: 900
parent_id: null
depth: 0
---

# FW-002 — AgentCrew passes results between agents as TEXT (extracted string + human-readable summary); loop stop is LLM-evaluated

## Summary

`AgentCrew` (`bots/flows/crew/crew.py`) has `run_sequential / run_loop / run_parallel / run_flow / run`. Hand-off is textual: `_extract_result(response)` ('Extract result string from response'), `_build_context_summary(context)` ('human-readable summary of results accumulated so far'), `_truncate_text`, `_build_shared_state_summary(shared_state)`, `_build_loop_first_agent_prompt`. Loop termination: `run_loop(initial_task, condition, max_iterations, ...)` with `_evaluate_loop_condition()` = 'Ask the configured LLM whether the loop condition has been satisfied' (an LLM wake per iteration). Agents are exposed to the orchestrating LLM via `_register_agents_as_tools()` (AgentTool, FW-003); deterministic members exist via `add_tool_node(tool, node_id)`. State is `FlowContext` (TASK-980) with `shared_data`; results are `NodeResult`/`FlowResult`. Imports `ToolManager`, `AgentTool`, `AIMessage`, `AgentResponse`, `AgentStatus`. Confirms the source's premise: inter-agent traffic inside a crew is serialized text plus an LLM turn on both ends; there is no typed performative, no reply-obligation semantics, no per-conversation state machine.

## Citations

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

Line numbers for the hand-off methods were not confirmed in this lane (API outline only). `[cross-lane: type=grep, intent=line ranges for _extract_result/_build_context_summary/_evaluate_loop_condition in crew.py]` (Q026/Q027 cover this). Related docs: `docs/architecture/07-agentcrew.md`, `sdd/specs/agentcrew-hooks.spec.md` (on_complete/on_error hooks exist — a telemetry attach point).
