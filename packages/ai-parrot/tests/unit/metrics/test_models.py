"""Tests for metric definition models (FEAT-756 M1)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

import parrot.metrics as pm
from parrot.metrics.models import KPICardShape, MetricDefinition, PeriodBinding, SemanticMetricSource


def test_metric_definition_roundtrip(worked_hours_def: MetricDefinition) -> None:
    """Metric definitions round-trip through JSON-compatible dictionaries."""
    dumped = worked_hours_def.model_dump(mode="json")
    again = MetricDefinition.model_validate(dumped)
    assert again == worked_hours_def
    assert isinstance(again.default_shape, KPICardShape)
    assert again.source.kind == "query_slug"


def test_metric_definition_rejects_public_tenant(worked_hours_def: MetricDefinition) -> None:
    """Public definitions cannot be scoped to a tenant."""
    data = worked_hours_def.model_dump(mode="json") | {"tenant": "acme", "visibility": "public"}
    with pytest.raises(ValidationError):
        MetricDefinition.model_validate(data)
    with pytest.raises(ValidationError):
        MetricDefinition.model_validate(worked_hours_def.model_dump(mode="json") | {"tenant": "invalid/name"})


def test_higher_is_better_tristate(worked_hours_def: MetricDefinition) -> None:
    """The tri-state value preserves false and null, and defaults to true."""
    base = worked_hours_def.model_dump(mode="json")
    assert MetricDefinition.model_validate(base | {"higher_is_better": False}).higher_is_better is False
    assert MetricDefinition.model_validate(base | {"higher_is_better": None}).higher_is_better is None
    assert MetricDefinition.model_validate(base | {"higher_is_better": True}).higher_is_better is True
    del base["higher_is_better"]
    assert MetricDefinition.model_validate(base).higher_is_better is True


def test_semantic_metric_parses(worked_hours_def: MetricDefinition) -> None:
    """Reserved semantic-metric sources parse and round-trip without execution."""
    data = worked_hours_def.model_dump(mode="json") | {
        "source": {"kind": "semantic_metric", "model": "finance", "metric": "worked_hours"}
    }
    definition = MetricDefinition.model_validate(data)
    assert isinstance(definition.source, SemanticMetricSource)
    assert MetricDefinition.model_validate(definition.model_dump(mode="json")) == definition


def test_period_binding_exactly_one_mode() -> None:
    """Bindings require a placeholder pair or a date column, exclusively."""
    assert PeriodBinding(start_placeholder="firstdate", end_placeholder="lastdate").date_column is None
    assert PeriodBinding(date_column="work_date").date_column == "work_date"
    for value in ({}, {"start_placeholder": "firstdate"}, {"end_placeholder": "lastdate"}, {
        "start_placeholder": "firstdate", "end_placeholder": "lastdate", "date_column": "work_date"
    }):
        with pytest.raises(ValidationError):
            PeriodBinding.model_validate(value)


def test_extra_field_forbidden(worked_hours_def: MetricDefinition) -> None:
    """Unknown model fields are rejected instead of silently accepting YAML typos."""
    with pytest.raises(ValidationError):
        MetricDefinition.model_validate(worked_hours_def.model_dump(mode="json") | {"unknown": "value"})


def test_matching_terms_and_dimension(worked_hours_def: MetricDefinition) -> None:
    """Terms normalize deterministically and dimensions resolve aliases case-insensitively."""
    worked_hours_def.aliases.append("  WORKED HOURS  ")
    assert worked_hours_def.matching_terms() == [
        "worked hours",
        "hours worked",
        "horas trabajadas",
        "worked hrs",
        "show me worked hours this month",
        "cuántas horas trabajamos este mes",
    ]
    assert worked_hours_def.dimension("CC").name == "cost center"
    assert worked_hours_def.dimension("missing") is None


def test_lazy_exports() -> None:
    """Package exports resolve lazily and unknown names fail normally."""
    assert pm.MetricDefinition is MetricDefinition
    with pytest.raises(AttributeError):
        pm.DoesNotExist  # noqa: B018
