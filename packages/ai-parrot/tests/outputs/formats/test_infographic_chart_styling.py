"""Chart styling tests for InfographicHTMLRenderer._build_echarts_option.

Covers the PowerBI-inspired refinements:
  - sign-based bar coloring (green up / red down) for variance charts
  - no in-canvas ECharts title (the <h3> header is the single title) so it
    cannot overlap the legend; legend pinned top-right
  - smooth (curved) line / area charts
"""
import pytest

from parrot.outputs.formats.infographic_html import (
    InfographicHTMLRenderer,
    _DEFAULT_POSITIVE_COLOR,
    _DEFAULT_NEGATIVE_COLOR,
    _BAR_BORDER_RADIUS,
    _CURRENCY_FORMATTER_TOKEN,
    _DEFAULT_PRIMARY_COLOR,
    _DEFAULT_SPLITLINE_COLOR,
    _LINE_SYMBOL_SIZE,
)
from parrot.models.infographic import (
    ChartBlock,
    ChartDataSeries,
    InfographicResponse,
    theme_registry,
)


@pytest.fixture
def renderer():
    r = InfographicHTMLRenderer()
    # _build_echarts_option reads the active theme for palette colors; it is
    # normally set inside render_to_html().
    r._theme_cfg = theme_registry.get("light")
    return r


def _chart(chart_type, values, **kwargs):
    return ChartBlock(
        chart_type=chart_type,
        title=kwargs.pop("title", "T"),
        labels=kwargs.pop("labels", [f"d{i}" for i in range(len(values))]),
        series=[ChartDataSeries(name=kwargs.pop("name", "s"), values=values)],
        **kwargs,
    )


class TestNoInCanvasTitle:
    def test_no_title_key(self, renderer):
        opt = renderer._build_echarts_option(_chart("bar", [1.0, 2.0]))
        assert "title" not in opt  # the <h3> header is the only title

    def test_legend_pinned_top_right(self, renderer):
        opt = renderer._build_echarts_option(_chart("bar", [1.0, 2.0]))
        assert opt["legend"]["top"] == 0
        assert opt["legend"]["right"] == 0
        assert opt["legend"]["textStyle"]["fontSize"] == 12

    def test_grid_leaves_top_headroom(self, renderer):
        opt = renderer._build_echarts_option(_chart("line", [1.0, 2.0]))
        assert opt["grid"]["top"] == 40
        assert opt["grid"]["containLabel"] is True


class TestSignColoredBars:
    def test_bars_with_negatives_are_sign_colored(self, renderer):
        opt = renderer._build_echarts_option(_chart("bar", [1200.0, -150.0, 50.0]))
        colors = [d["itemStyle"]["color"] for d in opt["series"][0]["data"]]
        assert colors == ["#10b981", "#ef4444", "#10b981"]  # light theme accents

    def test_zero_counts_as_positive(self, renderer):
        opt = renderer._build_echarts_option(_chart("bar", [0.0, -1.0]))
        colors = [d["itemStyle"]["color"] for d in opt["series"][0]["data"]]
        assert colors == ["#10b981", "#ef4444"]

    def test_positive_only_bars_are_not_recolored(self, renderer):
        """All-positive bars keep raw values (no per-bar override)."""
        opt = renderer._build_echarts_option(_chart("bar", [100.0, 200.0]))
        assert opt["series"][0]["data"] == [100.0, 200.0]

    def test_explicit_series_color_wins_over_sign_coloring(self, renderer):
        block = ChartBlock(
            chart_type="bar",
            title="T",
            labels=["a", "b"],
            series=[ChartDataSeries(name="s", values=[1.0, -1.0], color="#123456")],
        )
        opt = renderer._build_echarts_option(block)
        # Explicit color is honored (no per-bar sign coloring); data stays raw.
        assert opt["series"][0]["itemStyle"]["color"] == "#123456"
        assert opt["series"][0]["data"] == [1.0, -1.0]

    def test_none_values_preserved_without_color(self, renderer):
        opt = renderer._build_echarts_option(_chart("bar", [None, -5.0, 5.0]))
        data = opt["series"][0]["data"]
        assert data[0] == {"value": None}
        assert data[1]["itemStyle"]["color"] == "#ef4444"

    def test_falls_back_to_default_colors_without_theme(self):
        r = InfographicHTMLRenderer()
        r._theme_cfg = None  # no active theme
        opt = r._build_echarts_option(_chart("bar", [1.0, -1.0]))
        colors = [d["itemStyle"]["color"] for d in opt["series"][0]["data"]]
        assert colors == [_DEFAULT_POSITIVE_COLOR, _DEFAULT_NEGATIVE_COLOR]


class TestSmoothLines:
    def test_line_is_smooth(self, renderer):
        opt = renderer._build_echarts_option(_chart("line", [1.0, 2.0, 3.0]))
        assert opt["series"][0]["smooth"] is True

    def test_area_is_smooth(self, renderer):
        opt = renderer._build_echarts_option(_chart("area", [1.0, 2.0, 3.0]))
        assert opt["series"][0]["smooth"] is True
        assert opt["series"][0]["type"] == "line"
        # area charts now carry a gradient fill (see TestLineGradientFill)
        assert "areaStyle" in opt["series"][0]

    def test_bar_is_not_smoothed(self, renderer):
        opt = renderer._build_echarts_option(_chart("bar", [1.0, 2.0]))
        assert "smooth" not in opt["series"][0]


class TestLineSymbolSize:
    def test_line_has_small_symbols(self, renderer):
        opt = renderer._build_echarts_option(_chart("line", [1.0, 2.0]))
        assert opt["series"][0]["symbolSize"] == _LINE_SYMBOL_SIZE

    def test_area_has_small_symbols(self, renderer):
        opt = renderer._build_echarts_option(_chart("area", [1.0, 2.0]))
        assert opt["series"][0]["symbolSize"] == _LINE_SYMBOL_SIZE

    def test_bar_has_no_symbol_size(self, renderer):
        opt = renderer._build_echarts_option(_chart("bar", [1.0, 2.0]))
        assert "symbolSize" not in opt["series"][0]


class TestRoundedBars:
    _TOP = [_BAR_BORDER_RADIUS, _BAR_BORDER_RADIUS, 0, 0]
    _BOTTOM = [0, 0, _BAR_BORDER_RADIUS, _BAR_BORDER_RADIUS]

    def test_positive_only_bars_top_rounded(self, renderer):
        opt = renderer._build_echarts_option(_chart("bar", [1.0, 2.0]))
        assert opt["series"][0]["itemStyle"]["borderRadius"] == self._TOP

    def test_explicit_color_bars_top_rounded(self, renderer):
        block = ChartBlock(
            chart_type="bar", title="T", labels=["a", "b"],
            series=[ChartDataSeries(name="s", values=[1.0, 2.0], color="#123456")],
        )
        opt = renderer._build_echarts_option(block)
        assert opt["series"][0]["itemStyle"]["color"] == "#123456"
        assert opt["series"][0]["itemStyle"]["borderRadius"] == self._TOP

    def test_sign_bars_round_away_from_axis(self, renderer):
        opt = renderer._build_echarts_option(_chart("bar", [10.0, -10.0]))
        data = opt["series"][0]["data"]
        assert data[0]["itemStyle"]["borderRadius"] == self._TOP      # positive → top
        assert data[1]["itemStyle"]["borderRadius"] == self._BOTTOM   # negative → bottom

    def test_line_has_no_border_radius(self, renderer):
        opt = renderer._build_echarts_option(_chart("line", [1.0, 2.0]))
        assert "borderRadius" not in opt["series"][0].get("itemStyle", {})


class TestCurrencyAxis:
    def test_currency_axis_detected_by_dollar_label(self, renderer):
        block = _chart("bar", [1000.0, 2000.0], y_axis_label="$ change")
        opt = renderer._build_echarts_option(block)
        assert opt["yAxis"]["axisLabel"]["formatter"] == _CURRENCY_FORMATTER_TOKEN
        assert opt["tooltip"]["valueFormatter"] == _CURRENCY_FORMATTER_TOKEN

    def test_currency_applies_to_line_axis(self, renderer):
        block = _chart("line", [1e6, 2e6], y_axis_label="Total revenue ($)")
        opt = renderer._build_echarts_option(block)
        assert opt["yAxis"]["axisLabel"]["formatter"] == _CURRENCY_FORMATTER_TOKEN

    def test_non_currency_axis_has_no_formatter(self, renderer):
        block = _chart("bar", [1.0, 2.0], y_axis_label="units")
        opt = renderer._build_echarts_option(block)
        assert "axisLabel" not in opt["yAxis"]
        assert "valueFormatter" not in opt["tooltip"]

    def test_missing_axis_label_is_not_currency(self, renderer):
        opt = renderer._build_echarts_option(_chart("bar", [1.0, 2.0]))
        assert "axisLabel" not in opt["yAxis"]

    def test_token_swapped_for_js_function_in_html(self):
        """End-to-end: the sentinel token must become a real JS function."""
        r = InfographicHTMLRenderer()
        resp = InfographicResponse(template="executive", theme="light", blocks=[
            {"type": "title", "title": "T", "date": "x"},
            {"type": "chart", "chart_type": "bar", "title": "Rev",
             "y_axis_label": "$ change", "labels": ["d1", "d2"],
             "series": [{"name": "rev", "values": [1_200_000.0, -150_000.0]}]},
        ])
        html = r.render_to_html(resp, theme="light")
        assert _CURRENCY_FORMATTER_TOKEN not in html       # no leaked sentinel
        assert "function(value)" in html                   # real JS function
        assert "toFixed(2)+'M'" in html and "toFixed(1)+'K'" in html


class TestLineGradientFill:
    def test_single_series_line_has_vertical_gradient(self, renderer):
        opt = renderer._build_echarts_option(_chart("line", [1.0, 2.0, 3.0]))
        area = opt["series"][0]["areaStyle"]
        assert area["color"]["type"] == "linear"
        assert area["color"]["y"] == 0 and area["color"]["y2"] == 1  # top→bottom
        stops = area["color"]["colorStops"]
        assert stops[0]["offset"] == 0 and stops[1]["offset"] == 1
        # Fades to (near) transparent at the bottom.
        assert stops[0]["color"].endswith("0.28)")
        assert stops[1]["color"].endswith("0.02)")

    def test_line_color_aligned_to_gradient_base(self, renderer):
        """Without an explicit color, the line + fill share the theme primary."""
        opt = renderer._build_echarts_option(_chart("line", [1.0, 2.0]))
        assert opt["series"][0]["itemStyle"]["color"] == _DEFAULT_PRIMARY_COLOR

    def test_explicit_line_color_drives_gradient(self, renderer):
        block = ChartBlock(
            chart_type="line", title="T", labels=["a", "b"],
            series=[ChartDataSeries(name="s", values=[1.0, 2.0], color="#ff8800")],
        )
        opt = renderer._build_echarts_option(block)
        top = opt["series"][0]["areaStyle"]["color"]["colorStops"][0]["color"]
        assert top == "rgba(255,136,0,0.28)"

    def test_multi_series_line_has_no_fill(self, renderer):
        block = ChartBlock(
            chart_type="line", title="T", labels=["a", "b"],
            series=[
                ChartDataSeries(name="s1", values=[1.0, 2.0]),
                ChartDataSeries(name="s2", values=[3.0, 4.0]),
            ],
        )
        opt = renderer._build_echarts_option(block)
        assert all("areaStyle" not in s for s in opt["series"])

    def test_area_chart_keeps_gradient(self, renderer):
        opt = renderer._build_echarts_option(_chart("area", [1.0, 2.0]))
        assert opt["series"][0]["areaStyle"]["color"]["type"] == "linear"

    def test_bar_has_no_area_fill(self, renderer):
        opt = renderer._build_echarts_option(_chart("bar", [1.0, 2.0]))
        assert "areaStyle" not in opt["series"][0]

    def test_non_hex_color_falls_back_to_flat_fill(self, renderer):
        block = ChartBlock(
            chart_type="line", title="T", labels=["a", "b"],
            series=[ChartDataSeries(name="s", values=[1.0, 2.0], color="rgb(10,20,30)")],
        )
        opt = renderer._build_echarts_option(block)
        assert opt["series"][0]["areaStyle"] == {"opacity": 0.08}


class TestYAxisSplitLine:
    def test_bar_has_subtle_splitline(self, renderer):
        opt = renderer._build_echarts_option(_chart("bar", [1.0, 2.0]))
        sl = opt["yAxis"]["splitLine"]
        assert sl["show"] is True
        assert sl["lineStyle"]["color"] == "#e2e8f0"  # light theme neutral_border

    def test_line_has_subtle_splitline(self, renderer):
        opt = renderer._build_echarts_option(_chart("line", [1.0, 2.0]))
        assert opt["yAxis"]["splitLine"]["lineStyle"]["color"] == "#e2e8f0"

    def test_splitline_falls_back_without_theme(self):
        r = InfographicHTMLRenderer()
        r._theme_cfg = None
        opt = r._build_echarts_option(_chart("bar", [1.0, 2.0]))
        assert opt["yAxis"]["splitLine"]["lineStyle"]["color"] == _DEFAULT_SPLITLINE_COLOR


class TestToRgbaHelper:
    def test_six_digit_hex(self, renderer):
        assert renderer._to_rgba("#10b981", 0.5) == "rgba(16,185,129,0.5)"

    def test_three_digit_hex_expands(self, renderer):
        assert renderer._to_rgba("#abc", 0.1) == "rgba(170,187,204,0.1)"

    def test_non_hex_returns_none(self, renderer):
        assert renderer._to_rgba("rgb(1,2,3)", 0.5) is None
        assert renderer._to_rgba("tomato", 0.5) is None
