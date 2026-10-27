from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from parrot.metrics.errors import MetricSourceUnavailable
from parrot.metrics.models import DimensionSpec, MetricDefinition, ResolvedPeriod
from parrot_tools.metrics import executors as ex_mod
from parrot_tools.metrics.executors import (
    QuerySlugExecutor,
    RecipeExecutor,
    TransformerExecutor,
    executor_for,
)

PERIOD = ResolvedPeriod(
    preset="this_month",
    start=date(2026, 10, 1),
    end=date(2026, 10, 31),
    label="October 2026",
    udf_keywords={"start": "FDOM", "end": "LDOM"},
)


def _def(source: dict, binding: dict | None = None) -> MetricDefinition:
    return MetricDefinition.model_validate({
        "id": "worked_hours", "name": "Worked Hours",
        "time": {"binding": binding or {"start_placeholder": "firstdate", "end_placeholder": "lastdate"}},
        "default_shape": {"component": "KPICard", "value_column": "hours"}, "source": source})


def _qs(rows=None):
    return SimpleNamespace(execute_slug=AsyncMock(return_value=SimpleNamespace(
        rows=rows if rows is not None else [{"hours": 5}], columns=["hours"], applied_conditions={}, truncated=False)))


async def test_query_slug_executor_request():
    qs = _qs()
    frame = await QuerySlugExecutor(qs).fetch(_def({"kind": "query_slug", "slug": "flex_hours"}),
                                              period=PERIOD, dimension=None, filters={}, tenant=None)
    kwargs = qs.execute_slug.await_args.kwargs
    assert kwargs["placeholders"] == {"firstdate": "2026-10-01", "lastdate": "2026-10-31"}
    assert frame.rows == [{"hours": 5}]
    assert frame.linked_request is not None


async def test_query_slug_filters_and_dimension():
    qs = _qs()
    d = _def({"kind": "query_slug", "slug": "s", "filter": {"a": 1, "b": 2}, "fields": ["hours"],
              "grouping": ["x"]})
    await QuerySlugExecutor(qs).fetch(d, period=PERIOD, dimension=DimensionSpec(name="store", column="store_id"),
                                      filters={"b": 3}, tenant=None)
    kwargs = qs.execute_slug.await_args.kwargs
    assert kwargs["filter"] == {"a": 1, "b": 3}
    assert kwargs["grouping"] == ["x", "store_id"]
    assert kwargs["fields"] == ["hours", "store_id"]


async def test_query_slug_date_column_post_filter():
    qs = _qs([{"day": "2026-09-30", "hours": 1}, {"day": "2026-10-05", "hours": 2}])
    d = _def({"kind": "query_slug", "slug": "s"}, binding={"date_column": "day"})
    frame = await QuerySlugExecutor(qs).fetch(d, period=PERIOD, dimension=None, filters={}, tenant=None)
    assert frame.rows == [{"day": "2026-10-05", "hours": 2}]
    assert qs.execute_slug.await_args.kwargs["placeholders"] is None


def test_linked_request_uses_udf():
    req = QuerySlugExecutor(_qs()).linked_request(_def({"kind": "query_slug", "slug": "s"}), period=PERIOD)
    assert req["placeholders"] == {"firstdate": "FDOM", "lastdate": "LDOM"}
    no_udf = PERIOD.model_copy(update={"udf_keywords": None})
    req = QuerySlugExecutor(_qs()).linked_request(_def({"kind": "query_slug", "slug": "s"}), period=no_udf)
    assert req["placeholders"] == {"firstdate": "2026-10-01", "lastdate": "2026-10-31"}


async def test_transformer_executor_single_input(monkeypatch):
    monkeypatch.setattr(ex_mod, "validate_python_transform", lambda spec: [])

    async def fake_apply(frame, spec, *, max_rows):
        return pd.DataFrame({"hours": [frame["hours"].sum() * 2]})

    monkeypatch.setattr(ex_mod, "apply_python_transform", fake_apply)
    qs = _qs([{"hours": 2}, {"hours": 3}])
    d = _def({"kind": "transformer", "transformer": "double", "input": {"kind": "query_slug", "slug": "s"}})
    frame = await TransformerExecutor(qs).fetch(d, period=PERIOD, dimension=None, filters={}, tenant=None)
    assert frame.rows == [{"hours": 10}]
    assert frame.linked_request["placeholders"] == {"firstdate": "FDOM", "lastdate": "LDOM"}


async def test_transformer_executor_invalid(monkeypatch):
    monkeypatch.setattr(ex_mod, "validate_python_transform", lambda spec: ["multi-input"])
    qs = _qs()
    d = _def({"kind": "transformer", "transformer": "x", "input": {"kind": "query_slug", "slug": "s"}})
    with pytest.raises(ValueError, match="multi-input"):
        await TransformerExecutor(qs).fetch(d, period=PERIOD, dimension=None, filters={}, tenant=None)
    qs.execute_slug.assert_not_awaited()


async def test_recipe_executor_refuses_none_pctx():
    ex = RecipeExecutor(AsyncMock(), pctx_provider=lambda: None)
    d = _def({"kind": "recipe", "recipe_name": "flex", "data_model_path": "/payroll_hero/worked_hours_total"})
    with pytest.raises(PermissionError):
        await ex.fetch(d, period=PERIOD, dimension=None, filters={}, tenant=None)


@pytest.mark.parametrize("path,expected", [
    ("/payroll_hero/worked_hours_total", [{"hours": 42}]),
    ("/rows", [{"a": 1}, {"a": 2}]),
    ("/cols", [{"x": 1, "y": 3}, {"x": 2, "y": 4}]),
    ("/a~1b", [{"hours": 7}]),
])
async def test_recipe_executor_pointer_read(path, expected):
    data_model = {"payroll_hero": {"worked_hours_total": 42}, "rows": [{"a": 1}, {"a": 2}],
                  "cols": {"x": [1, 2], "y": [3, 4]}, "a/b": 7}
    runner = SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(
        metadata={"source_envelope": {"dataModel": data_model}})))
    ex = RecipeExecutor(runner, pctx_provider=lambda: object())
    d = _def({"kind": "recipe", "recipe_name": "flex", "data_model_path": path, "param_map": {"store": "store_id"}},
             binding={"start_placeholder": "month", "end_placeholder": "month_end"})
    frame = await ex.fetch(d, period=PERIOD, dimension=None, filters={"store": 9}, tenant=None)
    assert frame.rows == expected
    kwargs = runner.run.await_args.kwargs
    assert kwargs["include_envelope"] is True
    assert kwargs["params"] == {"store_id": 9, "month": "2026-10"}


def test_semantic_metric_unavailable():
    d = _def({"kind": "semantic_metric", "model": "m", "metric": "x"})
    with pytest.raises(MetricSourceUnavailable):
        executor_for(d.source, querysource=None, runner=None, pctx_provider=None)


def test_executor_for_dispatch():
    qs = _qs()
    assert isinstance(executor_for(_def({"kind": "query_slug", "slug": "s"}).source, querysource=qs, runner=None,
                                   pctx_provider=None), QuerySlugExecutor)
    with pytest.raises(ValueError):
        executor_for(_def({"kind": "recipe", "recipe_name": "r", "data_model_path": "/x"}).source,
                     querysource=None, runner=object(), pctx_provider=None)
