"""Result models of MetricsToolkit (spec §3 M5)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from parrot.metrics.models import MetricDefinition, ResolvedPeriod


class MetricSummary(BaseModel):
    """One row of ``list_metrics``."""

    id: str
    name: str
    unit: str | None = None
    default_component: str
    tenant: str | None = None
    program: str | None = None
    dimensions: list[str] = Field(default_factory=list)
    source_kind: str


class MetricExplanation(BaseModel):
    """Deterministic explanation of how a metric is computed."""

    definition: MetricDefinition
    lineage: str
    source_detail: Any = None


class QueryMetricResult(BaseModel):
    """Value, comparison and ready A2UI envelope of one metric query."""

    metric_id: str
    period: ResolvedPeriod
    comparison_period: ResolvedPeriod | None = None
    value: Any = None
    previous: Any = None
    delta: float | None = None
    delta_pct: float | None = None
    trend: Literal["up", "down", "flat"] | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    envelope: dict[str, Any]
    linked: bool = False
    surface_id: str | None = None
    duration_ms: int = 0
