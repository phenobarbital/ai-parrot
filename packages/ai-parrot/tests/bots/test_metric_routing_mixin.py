"""Tests for the metric default-shape routing slot (FEAT-756 M8)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from parrot.bots.mixins.intent_router import IntentRouterMixin
from parrot.bots.mixins.metric_routing import MetricRoutingMixin
from parrot.metrics.context import bind_metric_match, current_metric_match, reset_metric_match
from parrot.metrics.models import MetricDefinition, MetricMatch
from parrot.models.outputs import OutputMode
from parrot.registry.routing.embedding_router import RouteScore


class _SuperSentinel:
    """Terminal of the cooperative MRO that records whether it was reached."""

    def __init__(self, **kwargs):
        self.super_called = False
        super().__init__()

    async def _resolve_output_mode(self, query, ctx):
        self.super_called = True
        return None


class _Agent(IntentRouterMixin, MetricRoutingMixin, _SuperSentinel):
    """Correctly ordered routing chain used by the tests."""


class _WrongOrderAgent(MetricRoutingMixin, IntentRouterMixin, _SuperSentinel):
    """Intentionally inverted routing chain used to verify the warning."""


class _Ctx:
    """Minimal request context carrying output-routing state."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.output_mode = None
        self.intent_score = None
        self.a2ui_component = None


class _PhrasingRouter:
    """Deterministic phrasing router for precedence tests."""

    margin = 0.05

    def __init__(self):
        self.queries = []

    def route(self, query):
        self.queries.append(query)
        if "bar chart" in query:
            return RouteScore(OutputMode.STRUCTURED_CHART, 0.99, 0.10, False, "structured_chart", None)
        return RouteScore(None, 0.10, -1.0, False, None, None)


@pytest.fixture(autouse=True)
def _isolated_metric_match():
    """Restore metric-match ContextVar state after every test."""
    token = bind_metric_match(None)
    try:
        yield
    finally:
        reset_metric_match(token)


@pytest.fixture
def worked_hours_def() -> MetricDefinition:
    """Return a local worked-hours KPI definition."""
    return MetricDefinition.model_validate(
        {
            "id": "worked_hours",
            "name": "Worked Hours",
            "aliases": ["hours worked", "worked hours"],
            "example_phrases": ["show me worked hours this month"],
            "unit": "h",
            "format": "number",
            "higher_is_better": None,
            "program": "flex",
            "time": {
                "grain": "month",
                "default_period": "this_month",
                "series_grain": "day",
                "binding": {"start_placeholder": "firstdate", "end_placeholder": "lastdate"},
            },
            "comparison": {"mode": "previous_period"},
            "default_shape": {"component": "KPICard", "value_column": "hours", "aggregate": "sum"},
            "source": {"kind": "query_slug", "slug": "flex_hours"},
        }
    )


def _match(definition: MetricDefinition, *, score: float = 0.97) -> MetricMatch:
    """Build a deterministic metric match."""
    return MetricMatch(metric=definition, score=score, lane="alias", requested_period="this_month")


async def test_metric_routing_mixin_abstains_without_registry():
    agent = _Agent()
    ctx = _Ctx()

    result = await agent._resolve_output_mode("worked hours", ctx)

    assert result is None
    assert agent.super_called is True
    assert ctx.kwargs == {}


async def test_metric_routing_mixin_after_router_abstain(worked_hours_def, monkeypatch):
    match = _match(worked_hours_def)
    registry = AsyncMock()
    registry.resolve.return_value = match
    agent = _Agent(metric_registry=registry)
    ctx = _Ctx(tenant="acme")
    monkeypatch.setattr("parrot.bots.mixins.metric_routing.is_inline_component", lambda component: True)

    result = await agent._resolve_output_mode("worked hours this month", ctx)

    assert result == OutputMode.A2UI
    assert ctx.a2ui_component == "KPICard"
    assert ctx.kwargs["metric_match"] is match
    assert current_metric_match() is match
    assert ctx.intent_score == match.score
    registry.resolve.assert_awaited_once_with("worked hours this month", tenant="acme", user_id=None)


async def test_metric_routing_mixin_not_inline_returns_none(worked_hours_def, monkeypatch):
    match = _match(worked_hours_def)
    registry = AsyncMock()
    registry.resolve.return_value = match
    agent = _Agent(metric_registry=registry)
    ctx = _Ctx()
    monkeypatch.setattr("parrot.bots.mixins.metric_routing.is_inline_component", lambda component: False)

    result = await agent._resolve_output_mode("worked hours", ctx)

    assert result is None
    assert ctx.kwargs["metric_match"] is match
    assert current_metric_match() is match
    assert ctx.a2ui_component is None


async def test_metric_routing_mixin_honors_threshold(worked_hours_def):
    registry = AsyncMock()
    registry.resolve.return_value = _match(worked_hours_def, score=0.79)
    agent = _Agent(metric_registry=registry, metric_route_threshold=0.80)
    ctx = _Ctx()

    result = await agent._resolve_output_mode("worked hours", ctx)

    assert result is None
    assert "metric_match" not in ctx.kwargs
    assert current_metric_match() is None


async def test_metric_routing_mixin_registry_error_is_swallowed(caplog):
    registry = AsyncMock()
    registry.resolve.side_effect = RuntimeError("registry unavailable")
    agent = _Agent(metric_registry=registry)

    with caplog.at_level("WARNING"):
        result = await agent._resolve_output_mode("worked hours", _Ctx())

    assert result is None
    assert "metric routing failed: registry unavailable" in caplog.text


def test_metric_routing_mixin_mro_warning(caplog):
    with caplog.at_level("WARNING"):
        _WrongOrderAgent()

    assert "metric routing may outrank phrasing routing" in caplog.text


async def test_metric_turn_precedence(worked_hours_def, monkeypatch):
    match = _match(worked_hours_def)
    registry = AsyncMock()
    registry.resolve.return_value = match
    router = _PhrasingRouter()
    agent = _Agent(metric_registry=registry)
    agent._output_router = router
    monkeypatch.setattr("parrot.bots.mixins.metric_routing.is_inline_component", lambda component: True)

    phrasing_ctx = _Ctx()
    phrasing_result = await agent._resolve_output_mode("make a bar chart of hours", phrasing_ctx)
    assert phrasing_result == OutputMode.STRUCTURED_CHART
    registry.resolve.assert_not_awaited()

    metric_ctx = _Ctx()
    metric_result = await agent._resolve_output_mode("worked hours this month", metric_ctx)
    assert metric_result == OutputMode.A2UI
    assert metric_ctx.kwargs["metric_match"] is match

    explicit_ctx = _Ctx()
    explicit_mode = OutputMode.TEXT
    resolved = (
        await agent._resolve_output_mode("worked hours this month", explicit_ctx)
        if explicit_mode == OutputMode.DEFAULT
        else explicit_mode
    )
    assert resolved == OutputMode.TEXT
    assert len(router.queries) == 2
    assert registry.resolve.await_count == 1


async def test_metric_routing_mixin_passes_caller_to_registry(worked_hours_def):
    """The routing lane resolves as the caller, so the registry can hide others' private metrics."""
    registry = AsyncMock()
    registry.resolve.return_value = None
    agent = _Agent(metric_registry=registry)
    ctx = _Ctx(tenant="acme", user_id="u1")

    assert await agent._resolve_output_mode("worked hours this month", ctx) is None
    registry.resolve.assert_awaited_once_with("worked hours this month", tenant="acme", user_id="u1")
