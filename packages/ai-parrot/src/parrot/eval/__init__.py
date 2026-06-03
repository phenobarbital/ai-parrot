"""Generic Agent Evaluation Harness — public surface.

FEAT-217. All public names for the ``parrot.eval`` package are re-exported
from here so callers can do:

    from parrot.eval import EvalRunner, EvalTask, Trajectory, StateBasedEvaluator

``EvalTask.model_rebuild()`` is called here once ``SandboxSpec`` is available
to resolve the forward reference in the ``sandbox_spec`` field.
"""
from parrot.eval.models import (
    EvalDataset,
    EvalResult,
    EvalTask,
    MetricScore,
    TokenUsage,
    ToolCallRecord,
    Trajectory,
    TurnRecord,
)
from parrot.eval.registry import (
    get_evaluator,
    get_metric,
    list_evaluators,
    list_metrics,
    register_evaluator,
    register_metric,
)
from parrot.eval.sandbox.base import (
    AgentFactory,
    ExecResult,
    NoopSandbox,
    NoopSandboxProvider,
    Sandbox,
    SandboxProvider,
    SandboxSpec,
)
from parrot.eval.evaluators.base import AbstractEvaluator, Metric
from parrot.eval.sandbox.state import (
    DatabaseToolkitBinder,
    DictStateBackend,
    InMemoryStateSandbox,
    InMemoryStateSandboxProvider,
    JiraToolkitBinder,
    StateBackend,
    ToolkitBinder,
)

# Resolve the forward reference in EvalTask.sandbox_spec now that SandboxSpec
# is importable.
EvalTask.model_rebuild()

__all__ = [
    # models
    "EvalTask",
    "ToolCallRecord",
    "TurnRecord",
    "TokenUsage",
    "Trajectory",
    "MetricScore",
    "EvalResult",
    "EvalDataset",
    # registry
    "register_evaluator",
    "register_metric",
    "get_evaluator",
    "get_metric",
    "list_evaluators",
    "list_metrics",
    # sandbox ABCs
    "SandboxSpec",
    "ExecResult",
    "Sandbox",
    "SandboxProvider",
    "AgentFactory",
    "NoopSandbox",
    "NoopSandboxProvider",
    # state backend
    "StateBackend",
    "DictStateBackend",
    # evaluator ABCs
    "Metric",
    "AbstractEvaluator",
    # state sandbox + binders
    "ToolkitBinder",
    "InMemoryStateSandbox",
    "InMemoryStateSandboxProvider",
    "DatabaseToolkitBinder",
    "JiraToolkitBinder",
]
