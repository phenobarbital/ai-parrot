"""FEAT-423 (TASK-2221): ChartTool altair backend (replaces matplotlib default)."""
import json
from pathlib import Path

import pytest
from parrot.tools.chart import ChartFormat, ChartTool


@pytest.fixture
def chart_tool(tmp_path):
    """ChartTool instance with a temporary output directory, altair backend."""
    return ChartTool(output_dir=tmp_path, backend="altair")


@pytest.fixture
def bar_data():
    return {"categories": ["Q1", "Q2", "Q3", "Q4"], "values": [100, 150, 120, 180]}


class TestChartToolAltair:
    def test_default_backend_is_altair(self, tmp_path):
        tool = ChartTool(output_dir=tmp_path)
        assert tool.backend == "altair"

    def test_matplotlib_backend_rejected(self, tmp_path):
        with pytest.raises((ValueError, TypeError)):
            ChartTool(output_dir=tmp_path, backend="matplotlib")

    @pytest.mark.asyncio
    async def test_true_default_produces_vegalite_json(self, chart_tool, bar_data):
        """AC5: ChartTool() defaults to backend="altair" AND produces valid
        Vega-Lite JSON with NO explicit output_format — the default must not
        depend on whether the optional vl-convert-python is installed."""
        result = await chart_tool._execute(chart_type="bar", title="Revenue", data=bar_data)
        assert result.success
        chart_path = Path(result.metadata["chart_path"])
        assert chart_path.suffix == ".json"
        with open(chart_path) as f:
            spec = json.load(f)
        assert "$schema" in spec

    @pytest.mark.asyncio
    async def test_bar_chart_vegalite(self, chart_tool, bar_data):
        result = await chart_tool._execute(
            chart_type="bar", title="Revenue", data=bar_data,
            output_format="vegalite"
        )
        assert result.success
        # Verify valid Vega-Lite JSON
        chart_path = result.metadata["chart_path"]
        with open(chart_path) as f:
            spec = json.load(f)
        assert "$schema" in spec

    @pytest.mark.asyncio
    async def test_all_chart_types(self, chart_tool):
        """Every ChartType produces valid output."""
        test_data = {
            "bar": {"categories": ["A", "B"], "values": [10, 20]},
            "line": {"x": [1, 2, 3], "y": [10, 20, 15]},
            "pie": {"labels": ["A", "B"], "values": [60, 40]},
            "scatter": {"x": [1, 2, 3], "y": [4, 5, 6]},
            "histogram": {"values": [1, 2, 2, 3, 3, 3]},
            "area": {"x": [1, 2, 3], "y": [10, 20, 15]},
            "horizontal_bar": {"categories": ["A", "B"], "values": [10, 20]},
            "heatmap": {"data": [[1, 2], [3, 4]], "x_labels": ["X1", "X2"], "y_labels": ["Y1", "Y2"]},
        }
        for chart_type, data in test_data.items():
            result = await chart_tool._execute(
                chart_type=chart_type, title=f"Test {chart_type}", data=data,
                output_format="vegalite"
            )
            assert result.success, f"Failed for {chart_type}: {result.error}"

    @pytest.mark.asyncio
    async def test_multi_series_line_chart(self, chart_tool):
        """Multi-series line data (list-of-lists `y`) produces valid output."""
        data = {
            "x": [1, 2, 3],
            "y": [[10, 20, 15], [5, 8, 12]],
            "series_labels": ["Series A", "Series B"],
        }
        result = await chart_tool._execute(
            chart_type="line", title="Multi-series", data=data,
            output_format="vegalite"
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_png_falls_back_to_vegalite_without_vl_convert(self, chart_tool, bar_data):
        """PNG/SVG export without vl-convert-python falls back to Vega-Lite JSON
        (spec Key Constraint) rather than raising — actual output suffix is
        reported honestly in metadata."""
        result = await chart_tool._execute(
            chart_type="bar", title="Revenue", data=bar_data,
            output_format="png"
        )
        assert result.success
        chart_path = Path(result.metadata["chart_path"])
        # Either PNG succeeded (vl-convert-python installed) or it fell back
        # to a valid Vega-Lite JSON file — never a hard failure either way.
        assert chart_path.suffix in (".png", ".json")
        assert result.metadata["format"] == chart_path.suffix.lstrip(".")

    def test_no_matplotlib_methods(self, chart_tool):
        """matplotlib methods must not exist."""
        assert not hasattr(chart_tool, "_generate_matplotlib")
        assert not hasattr(chart_tool, "_matplotlib_render")

    def test_no_executor_class_var(self, chart_tool):
        """The matplotlib-only ThreadPoolExecutor class variable must be gone."""
        assert not hasattr(ChartTool, "_executor")

    def test_vegalite_json_format_enum_exists(self):
        assert ChartFormat.VEGALITE_JSON == "vegalite"

    @pytest.mark.asyncio
    async def test_generate_chart_invalid_type(self, chart_tool):
        """Invalid chart type is still reported as an error result."""
        result = await chart_tool._execute(
            chart_type="invalid_type", title="Invalid",
            data={"x": [1, 2], "y": [3, 4]},
        )
        assert result.success is False
        assert "Unsupported chart type" in result.error


class TestChartToolPlotly:
    @pytest.mark.asyncio
    async def test_plotly_still_works(self, tmp_path):
        tool = ChartTool(output_dir=tmp_path, backend="plotly")
        result = await tool._execute(
            chart_type="bar", title="Test", data={"categories": ["A"], "values": [1]},
            output_format="html"
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_plotly_pie_chart(self, tmp_path):
        tool = ChartTool(output_dir=tmp_path, backend="plotly")
        result = await tool._execute(
            chart_type="pie", title="Color Distribution",
            data={"labels": ["Red", "Blue", "Green"], "values": [30, 50, 20]},
            output_format="html",
        )
        assert result.success
        chart_path = Path(result.metadata["chart_path"])
        assert chart_path.exists()
