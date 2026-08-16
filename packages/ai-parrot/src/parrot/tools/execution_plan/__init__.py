"""``ExecutionPlanToolkit`` — deterministic tool-call DAGs for a ``BasicAgent``.

See ``sdd/specs/execution-plan-tool.spec.md`` (FEAT-419) for the full
design. This package wraps the frozen ``parrot.bots.flows.plan`` module
(FEAT-419 TASK-2179) with the agent-facing toolkit.
"""
from .catalog import (
    ArgSummary,
    ToolCatalogEntry,
    build_catalog,
    check_allowlist,
    validate_with_allowlist,
)
from .models import (
    PlanArtifactsArgs,
    PlanExecuteArgs,
    PlanStatusArgs,
    PlanValidateArgs,
    RunningSummary,
    RunRecord,
)
from .planner import PlanAuthoringError, PlanPlanner, resolve_planner_client
from .store import PlanFileStore, PlanLoadError
from .toolkit import ExecutionPlanToolkit

__all__ = (
    "ArgSummary",
    "ExecutionPlanToolkit",
    "PlanArtifactsArgs",
    "PlanAuthoringError",
    "PlanExecuteArgs",
    "PlanFileStore",
    "PlanLoadError",
    "PlanPlanner",
    "PlanStatusArgs",
    "PlanValidateArgs",
    "RunRecord",
    "RunningSummary",
    "ToolCatalogEntry",
    "build_catalog",
    "check_allowlist",
    "resolve_planner_client",
    "validate_with_allowlist",
)
