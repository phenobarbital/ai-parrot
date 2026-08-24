---
id: F009
query_id: Q009,Q010,Q011,Q012
type: grep
intent: Verify the remaining reuse-inventory claims — scheduler, structured outputs, loaders, ToolNode/run_flow
executed_at: 2026-08-23T00:22:57Z
depth: 0
parent_id: null
---

# F009 — Loaders, structured outputs and the ToolNode/run_flow DAG all confirmed; the scheduler is confirmed but lives in a satellite

## Summary

Four reuse claims verified in one pass. All four named loaders exist. `StructuredOutputConfig`
and `ask(..., structured_output=Model)` are real and already used by shipped bots. `ToolNode`
and `run_flow` both exist — note `run_flow` is defined twice, on `AgentsFlow` and on
`AgentCrew`, so the source's "AgentCrew.run_flow" is one of two valid targets. The scheduler
claim needs a caveat: `parrot/scheduler/` in core is a 38-line lazy shim whose `schedule`
decorator resolves via `__getattr__` to `parrot.scheduler.manager` in the
**ai-parrot-server[scheduler]** satellite — it is unavailable on a core-only install.

## Citations

- path: `packages/ai-parrot/src/parrot/scheduler/__init__.py`
  lines: 1-20
  symbol: `schedule`
  excerpt: |
    """Agent Scheduler for AI-Parrot.
    The scheduler implementation (AgentSchedulerManager, decorators, ScheduleType)
    is part of the server layer (ai-parrot-server satellite).
    Use: pip install ai-parrot-server[scheduler]
    """
    _SERVER_CLASSES = {
        "schedule": ("parrot.scheduler.manager", "schedule"),
        "AgentSchedulerManager": ("parrot.scheduler.manager", "AgentSchedulerManager"),
    }

- path: `packages/ai-parrot/src/parrot/bots/base.py`
  lines: 722, 961, 987
  symbol: `StructuredOutputConfig`
  excerpt: |
    llm_kwargs["structured_output"] = StructuredOutputConfig(
    structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]] = None,

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/tool_node.py`
  lines: 168
  symbol: `ToolNode`
  excerpt: |
    class ToolNode(Node):

- path: `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py`
  lines: 3033
  symbol: `AgentCrew.run_flow`

- path: `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
  lines: 1059
  symbol: `AgentsFlow.run_flow`

- path: `packages/ai-parrot-loaders/src/parrot_loaders/pdfmark.py`
  lines: 31
  symbol: `PDFMarkdownLoader`

- path: `packages/ai-parrot-loaders/src/parrot_loaders/html.py`
  lines: 10
  symbol: `HTMLLoader`

- path: `packages/ai-parrot-loaders/src/parrot_loaders/web.py`
  lines: 176
  symbol: `WebLoader`

- path: `packages/ai-parrot-loaders/src/parrot_loaders/markdown.py`
  lines: 11
  symbol: `MarkdownLoader`

- path: `packages/ai-parrot/src/parrot/tools/vectorstoresearch.py`
  lines: 48
  symbol: `VectorStoreSearchTool`

## Notes

Daily BOE/EUR-Lex sync therefore implies an ai-parrot-server dependency, or an external cron
calling an ingestion entrypoint. Worth stating explicitly in the spec.
