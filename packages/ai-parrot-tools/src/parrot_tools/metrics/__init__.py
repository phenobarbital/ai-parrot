"""Metric registry tools (FEAT-756): periods, shape emitter, source executors and MetricsToolkit."""

from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, str] = {
    "MetricsToolkit": ".toolkit",
    "QueryMetricResult": ".models",
    "MetricSummary": ".models",
    "MetricExplanation": ".models",
    "resolve_period": ".periods",
    "comparison_period": ".periods",
    "series_buckets": ".periods",
    "KPIFigures": ".shapes",
    "aggregate": ".shapes",
    "figures": ".shapes",
    "kpicard_props": ".shapes",
    "build_metric_envelope": ".shapes",
    "build_linked_metric_envelope": ".shapes",
    "SourceFrame": ".executors",
    "executor_for": ".executors",
    "QuerySlugExecutor": ".executors",
    "TransformerExecutor": ".executors",
    "RecipeExecutor": ".executors",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str) -> Any:
    """Resolve public names lazily from their submodule."""
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module, __name__), name)
    globals()[name] = value
    return value
