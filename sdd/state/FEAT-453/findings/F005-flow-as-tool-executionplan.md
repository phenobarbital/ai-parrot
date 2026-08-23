---
id: F005
query_id: Q009
type: read
intent: Confirm the mechanism by which an Agent invokes an AgentsFlow as a tool
executed_at: 2026-08-23T09:26:00Z
depth: 0
parent_id: null
---

# F005 — "Agent invokes a flow as a tool" is real, but it is `ExecutionPlanToolkit`, not a generic flow wrapper

## Summary

The source's premise ("un agente puede invocar un AgentsFlow como si fuera un
tool") is confirmed, with an important qualification about *which* mechanism.
Two distinct wrappers exist and they are not interchangeable:

1. `ExecutionPlanToolkit` (`parrot/tools/execution_plan/toolkit.py`) — an
   `AbstractToolkit` whose `plan_execute` tool runs a validated `ExecutionPlan`
   on `AgentsFlow` **with zero LLM tokens spent while it executes**, returning a
   bounded manifest. It has a run registry, soft timeouts, checkpoints,
   `plan_status`/`plan_artifacts` polling, a plan file store, an allowlist/
   catalog, and a `PlanPlanner`. This is the correct substrate for iterative
   bank-Excel expense ingestion.
2. `Agent.as_tool()` → `AgentTool` (`parrot/tools/agent.py:52`) — wraps an
   `AbstractBot`. `AgentsFlow` is **not** an `AbstractBot` (it is
   `AgentsFlow(PersistenceMixin)`), so `as_tool()` cannot wrap a flow.

So: an agent triggers a deterministic tool-call DAG via `ExecutionPlanToolkit`;
it composes *sub-agents* via `as_tool()`. There is no generic
`AgentsFlow.as_tool()`.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py`
  lines: 1-10
  symbol: "module docstring"
  excerpt: |
    ``ExecutionPlanToolkit`` — lets a plain ``BasicAgent`` trigger a deterministic
    tool-call DAG (``ExecutionPlan``) through a bounded tool call, with zero LLM
    tokens spent while it executes.

- path: `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py`
  lines: 62-70, 165-301, 385-500
  symbol: `ExecutionPlanToolkit`
  excerpt: |
    class ExecutionPlanToolkit(AbstractToolkit):
        async def _run_plan(...)            # line 165
        async def _execute_flow(self, flow: AgentsFlow, ...)   # line 284
            await flow.run_flow(ctx)        # line 301
        async def plan_status(self, run_id: str) -> ToolResult    # 385
        async def plan_artifacts(self, run_id: str) -> ToolResult # 408
        async def plan_execute(...)         # line 432
        async def plan_validate(...)        # line 462

- path: `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
  lines: 217
  symbol: `AgentsFlow`
  excerpt: |
    class AgentsFlow(PersistenceMixin):
        """DAG executor consuming ``parrot.bots.flows.core`` primitives.

- path: `packages/ai-parrot/src/parrot/tools/agent.py`
  lines: 52-75
  symbol: `AgentTool`
  excerpt: |
    class AgentTool(AbstractTool):
        """Wraps any BasicAgent/AbstractBot as a tool for use by other agents."""
        def __init__(self, agent: "AbstractBot", ...)

- path: `packages/ai-parrot/src/parrot/bots/agent.py`
  lines: 961-1000
  symbol: `Agent.as_tool`
  excerpt: |
    def as_tool(self, tool_name=None, tool_description=None, ...) -> "AgentTool":
        return AgentTool(agent=self, ...)

## Notes

`plan_status` + `plan_artifacts` polling is exactly the shape a Telegram
conversation needs for a long-running expense import: fire `plan_execute`,
return a run_id to the chat, poll and report progress, without holding the
chat turn open.
