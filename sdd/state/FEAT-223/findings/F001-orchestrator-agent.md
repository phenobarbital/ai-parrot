# F001 — OrchestratorAgent structure & ask() flow

**Path**: `packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py`
(monorepo; the path in the prompt `parrot/bots/flows/agents/orchestrator.py`
maps here). Class `OrchestratorAgent(BasicAgent)`, 340 lines.

## Citations
- `OrchestratorAgent.__init__` (L27-45): holds `self.agent_tools: Dict[str, AgentTool]`
  and `self.specialist_agents: Dict[str, BasicAgent|AbstractBot]`. Sets a default
  orchestration system prompt.
- `_set_default_orchestration_prompt` (L47-105): prompt ALREADY documents a
  "Sequential Chain (Cross-Pollination)" and "Iterative Refinement" strategy — but
  these are **LLM-driven**, sequential, prose-only (no structured voting).
- `add_agent` (L123-165): wraps an agent in `AgentTool`, stores it, registers it on
  `self.tool_manager`. `add_agent_by_name` (L167-197) resolves from `agent_registry`.
- `_init_execution_memory` (L199-204): creates one `ExecutionMemory(original_query=...)`
  and wires it into EVERY `AgentTool.execution_memory` — the shared cross-pollination bus.
- `_collect_agent_results` (L206-211): reads `memory.results` (dict of NodeResult).
- `ask` (L285-297): `_init_execution_memory()` → `super().ask()` (BasicAgent ReAct loop,
  LLM picks which AgentTools to call) → collect results → passthrough (1 agent) or
  `_build_synthesis_response` (merge data/artifacts/sources, metadata mode="synthesis").

## Relevance
The orchestrator's current model is **LLM-driven tool selection** — the LLM decides
which specialists to call. There is NO deterministic "broadcast to all + vote" path.
Multi-party conferencing must be a NEW method that iterates `self.specialist_agents`
directly, not relying on the ReAct loop. `_init_execution_memory` + `specialist_agents`
are the reuse anchors.
