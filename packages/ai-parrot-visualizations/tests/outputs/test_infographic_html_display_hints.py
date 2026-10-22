"""Infographic HTML lane honours display hints (FEAT-623, TASK-3997)."""

from __future__ import annotations

from parrot.models.infographic import ChartBlock, HeroCardBlock, TableBlock
from parrot.outputs.formats.infographic_html import InfographicHTMLRenderer


def _renderer() -> InfographicHTMLRenderer:
    return InfographicHTMLRenderer()


def _chart(**overrides) -> ChartBlock:
    payload = {
        "chart_type": "bar",
        "labels": ["a", "b"],
        "series": [{"name": "x", "values": [1, 2]}, {"name": "y", "values": [3, 4], "axis": "right"}],
        "y_axis_label": "Fallback",
        "y_axis_labels": ["Left", "Right"],
    }
    payload.update(overrides)
    return ChartBlock(**payload)


def test_hero_numeric_formatted():
    r = _renderer()
    assert "$1,203,456.00" in r._render_hero_card(HeroCardBlock(label="R", value=1203456, format="currency"))
    html = r._render_hero_card(HeroCardBlock(label="R", value=0.683, format="percent", unit="pts"))
    assert ">68.3%<" in html
    assert "3 visits" in r._render_hero_card(HeroCardBlock(label="R", value=3, format="number", unit="visits"))
    assert "3 visits" in r._render_hero_card(HeroCardBlock(label="R", value=3, unit="visits"))


def test_hero_zero_and_string_value():
    r = _renderer()
    assert ">0<" in r._render_hero_card(HeroCardBlock(label="R", value=0, format="number"))
    assert ">$3.7M<" in r._render_hero_card(HeroCardBlock(label="R", value="$3.7M", format="currency"))
    assert "&lt;b&gt;" in r._render_hero_card(HeroCardBlock(label="R", value="<b>"))


def test_table_numeric_column_formatted():
    block = TableBlock(
        columns=[
            {"header": "Plan"},
            {"header": "MRR", "type": "number", "format": "currency"},
            {"header": "Churn", "type": "number", "format": "percent", "align": "left"},
        ],
        rows=[["Pro", 1234.5, 0.683]],
    )
    html = _renderer()._render_table(block)
    assert '<td style="text-align:right">$1,234.50</td>' in html
    assert "<td>68.3%</td>" in html  # explicit align set -> no cell override
    assert "<td>Pro</td>" in html


def test_table_plain_columns_unchanged():
    html = _renderer()._render_table(TableBlock(columns=["A"], rows=[[1.2345]]))
    assert "<td>1.2345</td>" in html


def test_chart_right_axis_two_yaxes():
    option = _renderer()._build_echarts_option(_chart())
    assert isinstance(option["yAxis"], list) and len(option["yAxis"]) == 2
    assert option["yAxis"][0]["name"] == "Left" and option["yAxis"][1]["name"] == "Right"
    assert "yAxisIndex" not in option["series"][0]
    assert option["series"][1]["yAxisIndex"] == 1


def test_chart_without_right_axis_is_single_dict():
    block = _chart(series=[{"name": "x", "values": [1, 2]}], y_axis_labels=None)
    option = _renderer()._build_echarts_option(block)
    assert isinstance(option["yAxis"], dict)
    assert option["yAxis"]["name"] == "Fallback"
    assert all("yAxisIndex" not in s for s in option["series"])


def test_stacked_right_axis_series_not_stacked_into_left_total():
    option = _renderer()._build_echarts_option(_chart(stacked=True))
    assert option["series"][0]["stack"] == "total"
    assert "stack" not in option["series"][1]
