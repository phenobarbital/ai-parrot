# F002 — AgentTool: cross-pollination already half-built

**Path**: `packages/ai-parrot/src/parrot/tools/agent.py` — class `AgentTool(AbstractTool)`,
447 lines.

## Citations
- `QuestionInput` (L32-49): args schema with `question`, `mode` (replace|append),
  and **`include_previous_results: bool`** — "automatically inject all previous agent
  results as context into this agent call... for cross-pollination".
- `_execute` (L152-302): on `include_previous=True` and an execution_memory with results,
  prepends `_build_cross_pollination_context()` to the question, then calls the wrapped
  agent via `conversation()` (L220) / `ask()` (L228) / `invoke()` (L237). Writes an
  `AgentResult`/`NodeResult` into `self.execution_memory` (L271-295), preserving the full
  `AIMessage` (L250-258).
- `_build_cross_pollination_context` (L313-355): aggregates EVERY prior result in
  execution_memory into a "## Context from previous agents (cross-pollination)" block,
  truncating each to 2000 chars, **skipping the agent's own prior result** (L337-339) to
  avoid self-reference loops.

## Relevance
Cross-pollination CONTEXT injection already exists, but it is (a) sequential/incremental
(injects whatever ran before, in execution order), and (b) returns free-text, not a
structured vote. The "todos responden, luego se cruzan" simultaneous round + structured
"¿con cuál te quedas? + confidence" is NOT implemented. The new conferencing method can
reuse the `_build_cross_pollination_context` formatting idea but must (1) broadcast in
parallel first, then (2) re-prompt with structured_output for the vote.
