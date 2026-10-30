"""Metric definition registry (FEAT-756): tenant-scoped KPIs with a declared default shape.

Exports are lazy so importing ``parrot.metrics`` stays cheap and so sibling modules can be added
without editing this file.
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "MetricRegistryError": (".errors", "MetricRegistryError"),
    "MetricNotFound": (".errors", "MetricNotFound"),
    "MetricSourceUnavailable": (".errors", "MetricSourceUnavailable"),
    "MetricDefinition": (".models", "MetricDefinition"),
    "MetricMatch": (".models", "MetricMatch"),
    "MetricSource": (".models", "MetricSource"),
    "ShapeSpec": (".models", "ShapeSpec"),
    "ResolvedPeriod": (".models", "ResolvedPeriod"),
    "MetricStore": (".store", "MetricStore"),
    "InMemoryMetricStore": (".store", "InMemoryMetricStore"),
    "MetricsYamlReport": (".loader", "MetricsYamlReport"),
    "load_metrics_yaml": (".loader", "load_metrics_yaml"),
    "load_agent_metrics": (".loader", "load_agent_metrics"),
    "seed_store": (".loader", "seed_store"),
    "KpiTableRow": (".importers", "KpiTableRow"),
    "parse_kpi_table": (".importers", "parse_kpi_table"),
    "import_kpi_table": (".importers", "import_kpi_table"),
    "MetricMatcher": (".matching", "MetricMatcher"),
    "MetricRegistry": (".registry", "MetricRegistry"),
    "MetricView": (".registry", "MetricView"),
    "resolve_metric_tenant": (".context", "resolve_metric_tenant"),
    "current_metric_match": (".context", "current_metric_match"),
    "bind_metric_match": (".context", "bind_metric_match"),
    "reset_metric_match": (".context", "reset_metric_match"),
}

__all__ = sorted(_LAZY_IMPORTS)


def __getattr__(name: str) -> Any:
    """Lazily resolve a public metric-registry export."""
    try:
        module_name, attr = _LAZY_IMPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(importlib.import_module(module_name, __name__), attr)
    globals()[name] = value
    return value
