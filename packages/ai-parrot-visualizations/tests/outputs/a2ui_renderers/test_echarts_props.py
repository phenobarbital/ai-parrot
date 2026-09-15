"""Tests for FEAT-473 TASK-2564 — EChartsRenderer prop fidelity."""

import json

import pytest

pytest.importorskip("jsonpointer")

from parrot.outputs.a2ui.models import Component, CreateSurface
from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer

pytestmark = pytest.mark.asyncio


def _chart_component(**extra) -> Component:
    return Component(
        id="root",
        component="Chart",
        type="bar",
        x="month",
        y=["a", "b"],
        title="T",
        data={"path": "/rows"},
        **extra,
    )


def _envelope(component: Component) -> CreateSurface:
    return CreateSurface(
        surfaceId="main",
        catalogId="https://parrot.dev/catalogs/v1",
        components=[component],
        dataModel={"rows": [{"month": "Jan", "a": 1, "b": -2}, {"month": "Feb", "a": 2, "b": 3}]},
    )


async def test_echarts_honours_new_props():
    comp = _chart_component(
        stacked=True,
        splitSeries=True,
        trendline=True,
        colorBySign=True,
        negativeColor="#ff0000",
        positiveColor="#00ff00",
        xAxisLabel="Month",
        yAxisLabel="Value",
        palette=["#111111", "#222222"],
    )
    option = json.loads((await EChartsRenderer().render(_envelope(comp))).content)

    # stacked
    assert all(s["stack"] == "total" for s in option["series"] if s["type"] == "bar")
    # trendline — extra series appended
    assert any(s["name"].endswith("Trend") for s in option["series"])
    # colorBySign
    assert option["visualMap"]["pieces"][0]["color"] == "#ff0000"
    assert option["visualMap"]["pieces"][1]["color"] == "#00ff00"
    # Regression (post-review): series.data is a flat scalar array (not
    # [x,y] pairs) — the visualMap must target dimension 0, not 1, or the
    # sign-based coloring silently has no effect.
    assert option["visualMap"]["dimension"] == 0
    # axis labels
    assert isinstance(option["xAxis"], list)  # splitSeries -> multi-grid
    assert all(ax["name"] == "Month" for ax in option["xAxis"])
    assert all(ax["name"] == "Value" for ax in option["yAxis"])
    # palette
    assert option["color"] == ["#111111", "#222222"]
    # splitSeries -> multiple grids
    assert len(option["grid"]) == len(option["series"])


async def test_echarts_defaults_without_new_props():
    comp = _chart_component()
    option = json.loads((await EChartsRenderer().render(_envelope(comp))).content)

    assert isinstance(option["xAxis"], dict)
    assert "name" not in option["xAxis"]
    assert "stack" not in option["series"][0]
    assert "color" not in option
    assert "visualMap" not in option
    assert "grid" not in option
    assert len(option["series"]) == 2  # no trendline series appended


async def test_the_trend_line_is_grey_not_the_next_palette_colour():
    """A colour is a judgement in these reports; a regression is geometry.

    Left to ECharts the fitted line took the next palette entry, which in the
    FieldSync report came out red — an alarm nobody raised.
    """
    from parrot.outputs.a2ui_renderers.echarts import _TREND_COLOR

    comp = _chart_component(trendline=True)
    option = json.loads((await EChartsRenderer().render(_envelope(comp))).content)
    trend = [s for s in option["series"] if str(s["name"]).endswith("Trend")]
    assert len(trend) == 1
    assert trend[0]["lineStyle"]["color"] == _TREND_COLOR
    # The measured series keep whatever the palette gives them.
    assert all("lineStyle" not in s for s in option["series"] if not str(s["name"]).endswith("Trend"))


async def test_a_chart_can_combine_a_bar_and_a_line():
    """The brief's "barra + línea en el mismo gráfico".

    Until the contract could name a mark per series, a chart was one mark for
    everything — the requirement sat marked "Bloqueado (contrato)".
    """
    comp = _chart_component(seriesTypes=[None, "line"])
    option = json.loads((await EChartsRenderer().render(_envelope(comp))).content)
    assert [s["type"] for s in option["series"]] == ["bar", "line"]


async def test_a_series_gets_its_own_scale_only_when_it_asks():
    # A rate against a count on one axis lies flat along the floor and says
    # nothing; an unasked-for second axis is an empty ruler on every chart.
    comp = _chart_component(seriesTypes=[None, "line"], seriesAxes=[None, "right"])
    option = json.loads((await EChartsRenderer().render(_envelope(comp))).content)
    assert option["series"][0].get("yAxisIndex") is None
    assert option["series"][1]["yAxisIndex"] == 1
    assert isinstance(option["yAxis"], list)
    assert option["yAxis"][1]["position"] == "right"


async def test_a_chart_that_combines_nothing_is_untouched():
    comp = _chart_component()
    option = json.loads((await EChartsRenderer().render(_envelope(comp))).content)
    assert {s["type"] for s in option["series"]} == {"bar"}
    assert isinstance(option["yAxis"], dict)
