# F005 — Parallel execution primitive + prior art for deliberation

## AgentCrew.run_parallel (reusable fan-out pattern)
- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:1966` `async def run_parallel(...)`.
- Uses `asyncio.gather()` (L1979 docstring) over `tasks=[{agent_id, query}]`, builds an
  `ExecutionMemory` (L2013-2018), sets `execution_order` for "all agents at same level"
  (L2019-2020), supports an optional `synthesis_prompt`. This is the proven concurrent
  fan-out + synthesis shape the conference Round-0 broadcast should mirror.

## Prior art — same pattern already designed elsewhere
- `sdd/proposals/matrix-collaborative-crew.brainstorm.md`: phases
  **INVESTIGATE → CROSS-POLLINATE (1-N rounds) → SYNTHESIZE**; "the room IS the shared
  memory"; coordinator injects all agent responses as enriched context between rounds.
  Multi-party conferencing is the **in-process orchestrator analog** of that Matrix design.
- `sdd/proposals/massive-deliberation.md` (finance pipeline): Layer-2 DELIBERATION has
  "Phase 1: Cross-pollination" (Sub-A analysts → Sub-B receive A), "Phase 2: CIO-led
  deliberation (up to 3 rounds)", "Phase 3: Secretary → InvestmentMemo". Confidence-scored
  reasoning is already a domain concept (`models/outputs.py`, `models/detections.py`,
  `models/compliance.py` all carry `confidence`).

## Relevance
Both the concurrency primitive (`asyncio.gather`/`run_parallel`) and the conceptual
3-phase deliberation pattern already exist in the codebase. The new work is to land a
**generic, structured-vote** version of it directly on `OrchestratorAgent`, decoupled
from Matrix transport and from the finance domain.
