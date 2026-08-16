"""Deterministic execution plans for ai-parrot agents.

A thinking model authors an :class:`~.models.ExecutionPlan` once; the plan is
validated statically against the live ``ToolManager``, compiled to a
``FlowDefinition`` and executed by ``AgentsFlow`` with no LLM in the loop.
Tool payloads land in ``WorkingMemory``; only :class:`~.models.ArtifactRef`
facets travel back through the flow context.

Intended location in the repo::

    packages/ai-parrot/src/parrot/bots/flows/plan/
"""
from .compile import (
    END_NODE_ID,
    PLAN_NODE_TYPE,
    START_NODE_ID,
    ensure_tool_node_registered,
    to_flow_definition,
)
from .facets import estimate_bytes, extract_facets, merge_facets
from .guards import GuardCompilationError, PlanGuard, compile_guard
from .models import (
    ArtifactRef,
    ExecutionManifest,
    ExecutionPlan,
    FacetSpec,
    ForEach,
    PlanMetadata,
    PlanNode,
    RetryPolicy,
)
from .node import (
    PlanToolNode,
    ToolExecutionError,
    build_manifest,
    make_tool_node_factory,
)
from .paths import PathError, compile_path, render_key, select
from .validator import (
    PlanValidationError,
    ValidationIssue,
    ValidationReport,
    validate_plan,
)

__all__ = (
    "ArtifactRef",
    "END_NODE_ID",
    "ExecutionManifest",
    "ExecutionPlan",
    "FacetSpec",
    "ForEach",
    "GuardCompilationError",
    "PLAN_NODE_TYPE",
    "PathError",
    "PlanGuard",
    "PlanMetadata",
    "PlanNode",
    "PlanToolNode",
    "PlanValidationError",
    "RetryPolicy",
    "ToolExecutionError",
    "START_NODE_ID",
    "ValidationIssue",
    "ValidationReport",
    "build_manifest",
    "compile_guard",
    "compile_path",
    "ensure_tool_node_registered",
    "estimate_bytes",
    "extract_facets",
    "make_tool_node_factory",
    "merge_facets",
    "render_key",
    "select",
    "to_flow_definition",
    "validate_plan",
)
