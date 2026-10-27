"""Tests for the metric registry LLM toolkit."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from parrot.metrics.models import MetricDefinition
from parrot.metrics.store import InMemoryMetricStore
from parrot_tools.metrics.executors import SourceFrame
from parrot_tools.metrics.toolkit import MetricsToolkit


@pytest.fixture
def worked_hours() -> MetricDefinition:
    """Return a query-slug KPI definition used by the toolkit tests."""
    return MetricDefinition.model_validate(
        {
            "id": "worked_hours",
            "name": "Worked Hours",
            "unit": "h",
            "higher_is_better": None,
            "dimensions": [{"name": "cost center", "column": "cost_center"}],
            "time": {"binding": {"start_placeholder": "firstdate", "end_placeholder": "lastdate"}},
            "default_shape": {"component": "KPICard", "value_column": "hours"},
            "source": {"kind": "query_slug", "slug": "flex_hours"},
        }
    )


@pytest.fixture
def toolkit(worked_hours: MetricDefinition, monkeypatch: pytest.MonkeyPatch) -> MetricsToolkit:
    """Return a toolkit whose executor returns current then comparison data."""
    frames = iter([SourceFrame(rows=[{"hours": 110}]), SourceFrame(rows=[{"hours": 100}])])
    executor = SimpleNamespace(fetch=AsyncMock(side_effect=lambda *args, **kwargs: next(frames)))
    monkeypatch.setattr("parrot_tools.metrics.toolkit.executor_for", lambda *args, **kwargs: executor)
    return MetricsToolkit(store=InMemoryMetricStore([worked_hours]), querysource=AsyncMock())


def test_exactly_four_tools() -> None:
    """The public toolkit surface contains only the four specified tools."""
    names = {tool.name for tool in MetricsToolkit().get_tools()}
    assert names == {"list_metrics", "describe_metric", "query_metric", "explain_metric"}


async def test_query_metric_kpicard_end_to_end_stubbed(toolkit: MetricsToolkit) -> None:
    """KPI queries aggregate current and previous values into a tool envelope."""
    result = await toolkit.query_metric("worked_hours")
    assert result.value == 110
    assert result.previous == 100
    assert result.delta == 10
    assert result.trend == "up"
    assert result.envelope["components"][0]["component"] == "KPICard"


async def test_query_metric_by_dimension_switches_shape(
    toolkit: MetricsToolkit, worked_hours: MetricDefinition
) -> None:
    """A known breakdown dimension derives a chart; an unknown one is rejected."""
    executor = SimpleNamespace(fetch=AsyncMock(return_value=SourceFrame(rows=[{"cost_center": "a", "hours": 4}])))
    toolkit.registry = toolkit.registry.__class__(InMemoryMetricStore([worked_hours]))
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("parrot_tools.metrics.toolkit.executor_for", lambda *args, **kwargs: executor)
        result = await toolkit.query_metric("worked_hours", by="cost center")
    assert result.envelope["components"][0]["component"] == "Chart"
    with pytest.raises(ValueError, match="declared dimensions: cost center"):
        await toolkit.query_metric("worked_hours", by="missing")


async def test_query_metric_linked_only_for_query_slug(
    toolkit: MetricsToolkit, worked_hours: MetricDefinition, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Linked output uses the linked envelope builder and recipes get the documented error."""
    frame = SourceFrame(
        rows=[{"hours": 110}],
        linked_request={"placeholders": {"firstdate": "FDOM", "lastdate": "LDOM"}},
    )
    executor = SimpleNamespace(fetch=AsyncMock(side_effect=[frame, frame]))
    monkeypatch.setattr("parrot_tools.metrics.toolkit.executor_for", lambda *args, **kwargs: executor)
    linked = {"a2ui_envelope": {"metadata": {"extensions": {"parrot_data_sources": {}}}}}
    monkeypatch.setattr("parrot_tools.metrics.toolkit.build_linked_metric_envelope", AsyncMock(return_value=linked))
    result = await toolkit.query_metric("worked_hours", linked=True)
    assert result.linked is True
    recipe_payload = worked_hours.model_dump(mode="json")
    recipe_payload["source"] = {"kind": "recipe", "recipe_name": "r", "data_model_path": "/rows"}
    recipe = MetricDefinition.model_validate(recipe_payload)
    recipe_toolkit = MetricsToolkit(store=InMemoryMetricStore([recipe]), recipe_runner=AsyncMock(), pctx_provider=object)
    with pytest.raises(ValueError, match="only query_slug/transformer metrics can be linked"):
        await recipe_toolkit.query_metric("worked_hours", linked=True)


async def test_query_metric_pin_returns_surface_id_with_pin(toolkit: MetricsToolkit) -> None:
    """The pin flag persists a widget and returns the surface id."""
    publish_tool = SimpleNamespace(_execute=AsyncMock(return_value={"surface_id": "s1"}))
    toolkit._publish_tool = publish_tool
    result = await toolkit.query_metric("worked_hours", pin=True)
    assert result.surface_id == "s1"
    assert publish_tool._execute.await_args.kwargs["kind"] == "widget"


async def test_list_metrics_uses_request_tenant_and_rejects_invalid(
    worked_hours: MetricDefinition, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The execution hook validates explicit tenants and uses the request tenant by default."""
    scoped = worked_hours.model_copy(update={"tenant": "acme"})
    toolkit = MetricsToolkit(store=InMemoryMetricStore([scoped]))
    monkeypatch.setattr("parrot_tools.metrics.toolkit.current_context", lambda: SimpleNamespace(kwargs={"tenant": "acme"}))
    await toolkit._pre_execute("list_metrics")
    assert [metric.id for metric in await toolkit.list_metrics()] == ["worked_hours"]
    with pytest.raises(ValueError):
        await toolkit._pre_execute("list_metrics", tenant="../x")
