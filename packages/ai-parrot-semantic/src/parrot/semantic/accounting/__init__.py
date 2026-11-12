"""Accounting metrics layer: chart-of-accounts rollups compiled to deterministic queries (FEAT-713).

Every public name resolves lazily; the compile path (models, grammar, loader, validation, compiler,
evaluation) never imports the governed semantic stack.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, str] = {
    # errors (TASK-5524)
    "AccountingError": ".errors",
    "ModelValidationError": ".errors",
    "GrammarError": ".errors",
    "RequestValidationError": ".errors",
    "PeriodSpansMembershipChange": ".errors",
    "AccountingExecutionError": ".errors",
    "AccountingAuditError": ".errors",
    "Problem": ".errors",
    # compile path (TASK-5525..5531)
    "AccountingModel": ".models",
    "MetricRequest": ".models",
    "AssertionRequest": ".models",
    "MetricPlan": ".models",
    "CompiledMetricQuery": ".models",
    "Lineage": ".models",
    "MetricResult": ".models",
    "parse_expr": ".grammar",
    "load_model": ".loader",
    "plan_metric": ".compiler",
    "render_plan": ".compiler",
    "compile_metric": ".compiler",
    "evaluate_rows": ".evaluation",
    # runtime / governed side (TASK-5533..5537)
    "DuckDBRuntime": ".runtime.duckdb",
    "DatabaseRuntime": ".runtime.database",
    "AccountingAuditEntry": ".audit",
    "AccountingToolkit": ".toolkit",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    """Import the defining module on first use.

    Args:
        name: Public name requested on the package.

    Returns:
        The resolved public object.

    Raises:
        AttributeError: Unknown name, or its module is not importable yet.
    """
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    try:
        value = getattr(importlib.import_module(module, __name__), name)
    except ModuleNotFoundError as exc:
        raise AttributeError(f"{name!r} lives in {module!r}, which is not available: {exc}") from exc
    globals()[name] = value
    return value
