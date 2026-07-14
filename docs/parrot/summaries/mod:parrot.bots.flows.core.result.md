---
type: Wiki Summary
title: parrot.bots.flows.core.result
id: mod:parrot.bots.flows.core.result
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Flow Primitives — Result Models.
relates_to:
- concept: class:parrot.bots.flows.core.result.FlowResult
  rel: defines
- concept: class:parrot.bots.flows.core.result.NodeExecutionInfo
  rel: defines
- concept: class:parrot.bots.flows.core.result.NodeResult
  rel: defines
- concept: func:parrot.bots.flows.core.result.build_node_metadata
  rel: defines
- concept: func:parrot.bots.flows.core.result.determine_run_status
  rel: defines
- concept: mod:parrot.bots.flows.core.types
  rel: references
- concept: mod:parrot.models.responses
  rel: references
- concept: mod:parrot.tools.infographic_toolkit
  rel: references
---

# `parrot.bots.flows.core.result`

Flow Primitives — Result Models.

Provides ``FlowResult`` (replacing ``CrewResult``) and ``NodeExecutionInfo``
(replacing ``AgentExecutionInfo``) as the canonical result models for both
orchestration engines.

Also provides ``NodeResult`` (replacing ``AgentResult``) as the unified
per-node execution record for ``ExecutionMemory`` and FAISS vectorization.

All backward-compatible aliases are preserved so existing code importing
``CrewResult`` / ``AgentExecutionInfo`` continues to work via re-exports
in ``parrot.models.crew`` (wired up in TASK-920).

``AgentResult`` stays in ``parrot.models.crew`` for any remaining consumers.

## Classes

- **`NodeResult`** — Per-node execution record for storage and vectorization.
- **`NodeExecutionInfo`** — Execution metadata for a single node in a flow/crew run.
- **`FlowResult`** — Standardised result from a flow/crew execution.

## Functions

- `def determine_run_status(success_count: int, failure_count: int) -> Literal['completed', 'partial', 'failed']` — Compute the overall status for a crew/flow execution.
- `def build_node_metadata(node_id: str, agent: Optional[Any], response: Optional[Any], output: Optional[Any], execution_time: float, status: str, error: Optional[str]=None) -> NodeExecutionInfo` — Create execution metadata for a node run.
