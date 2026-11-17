---
id: FC-004
query_id: Q041
type: read
intent: "Read FlowContext / shared state in bots/flows/core (closest existing blackboard; single-writer, versioning?)."
executed_at: 2026-10-26T00:20:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# FC-004 — FlowContext shared_data is a plain dict, no versioning, no ACL

## Summary

`bots/flows/core/` contains `context.py`, `fsm.py`, `node.py`, `result.py`, `transition.py`, `types.py` (Q024 tree). `FlowContext` (dataclass, 365 lines) is the per-run state tracker shared by AgentCrew and AgentsFlow: `results`/`responses`/`node_metadata` keyed by node_id, completion sets, `errors`, and `shared_data: Dict[str, Any]` — an arbitrary key-value dict with no writer ownership, no version, no subscriptions and no ACL. It binds an optional `agent_registry` (resolve_agent by name via `get_bot_instance`) and a `trace_context` (W3C TraceContext, FEAT-176) and can snapshot itself for checkpointing (FEAT-399).

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/core/context.py`
  lines: 55-119
  symbol: `FlowContext`
  excerpt: |
    @dataclass
    class FlowContext:
        initial_task: str
        results: Dict[str, Any] = field(default_factory=dict)
        responses: Dict[str, Any] = field(default_factory=dict)
        node_metadata: Dict[str, NodeExecutionInfo] = field(default_factory=dict)
        shared_data: Dict[str, Any] = field(default_factory=dict)
        """Arbitrary key-value data shared across all nodes (replaces AgentContext.shared_data)."""
        agent_registry: Optional["AgentRegistry"] = field(default=None)
        trace_context: Optional["TraceContext"] = field(default=None)

- path: `packages/ai-parrot/src/parrot/bots/flows/core/context.py`
  lines: 123-159
  symbol: `FlowContext.resolve_agent`
  excerpt: |
    if self.agent_registry is None:
        raise AgentNotFoundError(...)
    agent = self.agent_registry.get_bot_instance(agent_ref)

- path: `packages/ai-parrot/src/parrot/bots/flows/core/context.py`
  lines: 259-283
  symbol: `FlowContext.get_input_for_node`
  excerpt: |
    return {"task": self.initial_task,
            "dependencies": {dep: self.results.get(dep) for dep in dependencies if dep in self.results}}

- path: `packages/ai-parrot/src/parrot/bots/flows/core/context.py`
  lines: 287-342
  symbol: `FlowContext.to_snapshot`
  excerpt: |
    return ContextSnapshot(initial_task=..., results=results_safe, responses=responses_safe,
        completed_tasks=sorted(self.completed_tasks), completion_order=list(self.completion_order),
        shared_data=dict(self.shared_data), errors=errors_structured)

- path: `packages/ai-parrot/src/parrot/bots/flows/flow/actions.py`
  lines: 309-320
  symbol: `SetContextAction`
  excerpt: |
    shared_context = ctx.get("shared_context")
    ...
    shared_context[self.config.key] = value


## Notes

Q044 (grep `blackboard|SharedMemory|shared_memory|shared_context|SharedContext|single_writer` over bots/flows + memory): only `shared_context` in `flows/flow/actions.py` (SetContextAction writes a key; TransformAction writes `_transformed_result`). No blackboard, no single-writer enforcement, no versioned write — the VERIFY claim holds. The closest seams for a blackboard are `FlowContext.shared_data` (in-process) and Matrix room state events (FC-007).
