---
id: F001
query_id: Q001
type: read
intent: Verify whether PlanToolNode and ExecutionPlan are already landed
executed_at: 2026-09-21T22:05:00Z
depth: 0
parent_id: null
---

# F001 — Plan module already landed (PlanToolNode, ExecutionPlan, ArtifactRef)

## Summary

The `packages/ai-parrot/src/parrot/bots/flows/plan/` package exists and exports PlanToolNode, make_tool_node_factory, ExecutionPlan, PlanNode, ForEach, ArtifactRef, validate_plan, and CEL guards. The proposal's "pending" dependency on `register_node("tool")(PlanToolNode)` is ALREADY RESOLVED (TASK-2179, commit d7b4819db). `ExecutionPlanToolkit._run_plan` also exists (TASK-2180). The `run_execution_plan` tool referenced in the proposal is live as `ExecutionPlanToolkit`.

## Citations

- path: `packages/ai-parrot/src/parrot/bots/flows/plan/__init__.py`
  lines: 1-50
  excerpt: |
    from .compile import (END_NODE_ID, PLAN_NODE_TYPE, START_NODE_ID,
        ensure_tool_node_registered, to_flow_definition)
    from .models import (ArtifactRef, ExecutionManifest, ExecutionPlan,
        FacetSpec, ForEach, PlanMetadata, PlanNode, RetryPolicy)
    from .node import (PlanToolNode, ToolExecutionError, build_manifest,
        make_tool_node_factory)
    from .validator import (PlanValidationError, ValidationIssue,
        ValidationReport, validate_plan)

- path: `packages/ai-parrot/src/parrot/bots/flows/plan/compile.py`
  lines: 133-154
  symbol: `ensure_tool_node_registered`
  excerpt: |
    def ensure_tool_node_registered(node_cls: Any) -> None:
        from parrot.bots.flows.flow.flow import NODE_REGISTRY, register_node
        if NODE_REGISTRY.get(PLAN_NODE_TYPE) is node_cls:
            return
        if PLAN_NODE_TYPE in NODE_REGISTRY:
            raise ValueError(...)
        register_node(PLAN_NODE_TYPE)(node_cls)

- path: `packages/ai-parrot/src/parrot/bots/flows/plan/node.py`
  lines: 1072-1121
  symbol: `make_tool_node_factory`
  excerpt: |
    def make_tool_node_factory(tool_manager, working_memory, *,
        permission_context=None, plan_run_id=None, step_mapping=None
    ) -> Callable[[Any, Set[str], Set[str]], PlanToolNode]:

## Notes

TASK-2179 (commit d7b4819db) landed the plan module. TASK-2180 landed the ExecutionPlanToolkit. The proposal's §9 "pending" items for `register_node("tool")` and `run_execution_plan` are resolved.
